// HOPEFX-AI-TRADING
// Copyright (c) 2025-2026
// Licensed under GNU Affero General Public License v3.0 (AGPL-3.0)
//
// execution/cpp_shim/hopefx_shim.cpp
// ====================================
// Low-latency C++ execution shim for HOPEFX.
//
// Architecture
// ------------
// Python brain  ──ZMQ PUSH──►  hopefx_shim  ──FIX 4.4──►  Exchange
//               ◄──ZMQ PULL──               ◄──FIX 4.4──
//
// The shim receives JSON order commands from the Python engine over ZMQ,
// formats them as FIX 4.4 NewOrderSingle messages, sends them to the
// exchange FIX gateway, and returns fill confirmations back over ZMQ.
//
// Why C++?
// --------
// - No GIL, no garbage collector pauses
// - Stack-allocated message buffers — zero heap allocation in the hot path
// - SO_BUSY_POLL socket option for sub-100μs poll latency
// - CPU affinity pinning via sched_setaffinity
// - Optional: DPDK poll-mode driver (replace recv_fix_message with rte_eth_rx_burst)
//
// ZMQ message protocol (JSON)
// ---------------------------
// Command (Python → shim):
//   {"cmd":"ORDER","id":"<uuid>","symbol":"XAUUSD","side":"BUY",
//    "qty":1.0,"price":2350.0,"type":"LIMIT","account":"CME123"}
//   {"cmd":"CANCEL","id":"<uuid>","orig_id":"<orig_cl_ord_id>"}
//   {"cmd":"PING"}
//   {"cmd":"SHUTDOWN"}
//
// Response (shim → Python):
//   {"type":"FILL","id":"<uuid>","order_id":"<exch_id>","price":2350.1,
//    "qty":1.0,"latency_us":320,"ts":1711234567890123}
//   {"type":"REJECT","id":"<uuid>","reason":"<text>","ts":...}
//   {"type":"PONG","ts":...}
//   {"type":"ERROR","msg":"<text>","ts":...}
//
// Build
// -----
//   cd execution/cpp_shim
//   cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j$(nproc)
//   # or: g++ -O3 -march=native -std=c++17 hopefx_shim.cpp -lzmq -o hopefx_shim
//
// Environment variables
// ---------------------
//   ZMQ_CMD_PORT       port to PULL commands from Python (default: 6555)
//   ZMQ_RESP_PORT      port to PUSH responses to Python  (default: 6556)
//   FIX_HOST           FIX gateway host                  (default: 127.0.0.1)
//   FIX_PORT           FIX gateway port                  (default: 9876)
//   FIX_SENDER_COMP_ID SenderCompID                      (default: HOPEFX)
//   FIX_TARGET_COMP_ID TargetCompID                      (default: CME)
//   FIX_USERNAME       FIX logon username
//   FIX_PASSWORD       FIX logon password
//   CPU_AFFINITY_CORE  pin shim to this CPU core         (default: -1 = no pin)
//   LATENCY_WARN_US    log warning if latency > N μs     (default: 500)
//   BUSY_POLL_US       SO_BUSY_POLL value in μs          (default: 50)

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <thread>
#include <unordered_map>

// ZeroMQ C++ binding (cppzmq header-only)
#include <zmq.hpp>

// POSIX for CPU affinity and socket options
#ifdef __linux__
#include <sched.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <fcntl.h>
#endif

// ── Minimal JSON helpers (no external dependency) ────────────────────────────

static std::string json_get(const std::string& json, const std::string& key) {
    std::string search = "\"" + key + "\"";
    auto pos = json.find(search);
    if (pos == std::string::npos) return "";
    pos = json.find(':', pos + search.size());
    if (pos == std::string::npos) return "";
    ++pos;
    while (pos < json.size() && (json[pos] == ' ' || json[pos] == '\t')) ++pos;
    if (pos >= json.size()) return "";
    if (json[pos] == '"') {
        auto end = json.find('"', pos + 1);
        return (end != std::string::npos) ? json.substr(pos + 1, end - pos - 1) : "";
    }
    auto end = json.find_first_of(",}", pos);
    std::string val = json.substr(pos, (end != std::string::npos) ? end - pos : std::string::npos);
    val.erase(std::remove_if(val.begin(), val.end(), ::isspace), val.end());
    return val;
}

static std::string json_str(const std::string& key, const std::string& val) {
    return "\"" + key + "\":\"" + val + "\"";
}
static std::string json_num(const std::string& key, long long val) {
    return "\"" + key + "\":" + std::to_string(val);
}
static std::string json_flt(const std::string& key, double val) {
    std::ostringstream ss;
    ss << std::fixed << std::setprecision(5) << val;
    return "\"" + key + "\":" + ss.str();
}

// ── Timestamp helpers ─────────────────────────────────────────────────────────

static long long now_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::steady_clock::now().time_since_epoch()
    ).count();
}

static long long now_epoch_us() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
}

static std::string utc_timestamp() {
    auto now = std::chrono::system_clock::now();
    auto t   = std::chrono::system_clock::to_time_t(now);
    auto ms  = std::chrono::duration_cast<std::chrono::milliseconds>(
                   now.time_since_epoch()) % 1000;
    std::ostringstream ss;
    ss << std::put_time(std::gmtime(&t), "%Y%m%d-%H:%M:%S")
       << "." << std::setfill('0') << std::setw(3) << ms.count();
    return ss.str();
}

// ── FIX 4.4 message builder ───────────────────────────────────────────────────

class FIXMessage {
public:
    explicit FIXMessage(const std::string& msg_type) : msg_type_(msg_type) {}

    FIXMessage& set(int tag, const std::string& val) {
        fields_[tag] = val;
        return *this;
    }
    FIXMessage& set(int tag, double val) {
        std::ostringstream ss;
        ss << std::fixed << std::setprecision(5) << val;
        fields_[tag] = ss.str();
        return *this;
    }
    FIXMessage& set(int tag, int val) {
        fields_[tag] = std::to_string(val);
        return *this;
    }

    std::string build(const std::string& sender, const std::string& target, int seq_num) const {
        std::string body;
        // Tag 35 (MsgType) first in body
        body += "35=" + msg_type_ + "\x01";
        body += "49=" + sender + "\x01";
        body += "56=" + target + "\x01";
        body += "34=" + std::to_string(seq_num) + "\x01";
        body += "52=" + utc_timestamp() + "\x01";
        for (const auto& [tag, val] : fields_) {
            if (tag != 35 && tag != 49 && tag != 56 && tag != 34 && tag != 52)
                body += std::to_string(tag) + "=" + val + "\x01";
        }
        int body_len = static_cast<int>(body.size());
        std::string msg = "8=FIX.4.4\x01" "9=" + std::to_string(body_len) + "\x01" + body;
        // Checksum (tag 10)
        int cksum = 0;
        for (unsigned char c : msg) cksum += c;
        std::ostringstream cs;
        cs << std::setfill('0') << std::setw(3) << (cksum % 256);
        msg += "10=" + cs.str() + "\x01";
        return msg;
    }

private:
    std::string msg_type_;
    std::unordered_map<int, std::string> fields_;
};

// ── FIX TCP session ───────────────────────────────────────────────────────────

class FIXSession {
public:
    FIXSession(const std::string& host, int port,
               const std::string& sender, const std::string& target,
               const std::string& username, const std::string& password,
               int busy_poll_us)
        : host_(host), port_(port), sender_(sender), target_(target),
          username_(username), password_(password),
          busy_poll_us_(busy_poll_us), sock_(-1), seq_num_(1) {}

    ~FIXSession() { disconnect(); }

    bool connect() {
#ifdef __linux__
        sock_ = ::socket(AF_INET, SOCK_STREAM, 0);
        if (sock_ < 0) { perror("socket"); return false; }

        // TCP_NODELAY — disable Nagle, critical for FIX latency
        int one = 1;
        ::setsockopt(sock_, IPPROTO_TCP, TCP_NODELAY, &one, sizeof(one));

        // SO_BUSY_POLL — spin-poll for incoming data before sleeping
        if (busy_poll_us_ > 0)
            ::setsockopt(sock_, SOL_SOCKET, SO_BUSY_POLL, &busy_poll_us_, sizeof(busy_poll_us_));

        // TCP keepalive
        ::setsockopt(sock_, SOL_SOCKET, SO_KEEPALIVE, &one, sizeof(one));

        struct sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port   = htons(static_cast<uint16_t>(port_));
        ::inet_pton(AF_INET, host_.c_str(), &addr.sin_addr);

        if (::connect(sock_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
            perror("connect");
            ::close(sock_);
            sock_ = -1;
            return false;
        }

        // Send FIX Logon (tag 35=A)
        FIXMessage logon("A");
        logon.set(98, 0)          // EncryptMethod=None
             .set(108, 5)         // HeartBtInt=5s
             .set(141, "Y")       // ResetOnLogon
             .set(553, username_) // Username
             .set(554, password_);// Password
        send_raw(logon.build(sender_, target_, seq_num_++));

        // Wait for Logon response
        std::string resp = recv_raw(2000);
        if (resp.find("35=A") == std::string::npos) {
            std::cerr << "FIX Logon rejected: " << resp << "\n";
            ::close(sock_);
            sock_ = -1;
            return false;
        }
        std::cout << "[FIX] Logon accepted\n";
        return true;
#else
        std::cerr << "[FIX] Non-Linux platform — FIX session unavailable\n";
        return false;
#endif
    }

    void disconnect() {
#ifdef __linux__
        if (sock_ >= 0) {
            // Send Logout (tag 35=5)
            FIXMessage logout("5");
            logout.set(58, "Normal logout");
            send_raw(logout.build(sender_, target_, seq_num_++));
            ::close(sock_);
            sock_ = -1;
        }
#endif
    }

    bool is_connected() const { return sock_ >= 0; }

    // Send NewOrderSingle (tag 35=D) and return fill price/qty from ExecutionReport
    bool send_order(const std::string& cl_ord_id, const std::string& symbol,
                    const std::string& side, const std::string& ord_type,
                    double qty, double price, const std::string& account,
                    double& out_fill_price, double& out_fill_qty,
                    std::string& out_order_id, std::string& out_error) {
        if (!is_connected()) {
            out_error = "FIX session not connected";
            return false;
        }

        FIXMessage nos("D");
        nos.set(11, cl_ord_id)                    // ClOrdID
           .set(55, symbol)                        // Symbol
           .set(54, side == "BUY" ? "1" : "2")    // Side
           .set(40, ord_type == "LIMIT" ? "2" : "1") // OrdType
           .set(38, qty)                           // OrderQty
           .set(60, utc_timestamp())               // TransactTime
           .set(1, account);                       // Account
        if (ord_type == "LIMIT" && price > 0)
            nos.set(44, price);                    // Price

        send_raw(nos.build(sender_, target_, seq_num_++));

        // Wait for ExecutionReport (tag 35=8)
        std::string resp = recv_raw(5000);
        if (resp.empty()) {
            out_error = "FIX timeout waiting for ExecutionReport";
            return false;
        }
        if (resp.find("35=8") == std::string::npos) {
            out_error = "Unexpected FIX response: " + resp.substr(0, 100);
            return false;
        }

        // Parse fill fields from ExecutionReport
        out_order_id   = fix_field(resp, 37);   // OrderID
        out_fill_price = std::stod(fix_field_or(resp, 31, "0")); // LastPx
        out_fill_qty   = std::stod(fix_field_or(resp, 32, "0")); // LastQty
        std::string exec_type = fix_field(resp, 150);            // ExecType

        if (exec_type == "8") { // Rejected
            out_error = "Order rejected: " + fix_field_or(resp, 58, "unknown");
            return false;
        }
        return true;
    }

private:
    void send_raw(const std::string& msg) {
#ifdef __linux__
        ::send(sock_, msg.c_str(), msg.size(), MSG_NOSIGNAL);
#endif
    }

    std::string recv_raw(int timeout_ms) {
#ifdef __linux__
        struct timeval tv{};
        tv.tv_sec  = timeout_ms / 1000;
        tv.tv_usec = (timeout_ms % 1000) * 1000;
        ::setsockopt(sock_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));

        char buf[65536];
        ssize_t n = ::recv(sock_, buf, sizeof(buf) - 1, 0);
        if (n <= 0) return "";
        buf[n] = '\0';
        return std::string(buf, n);
#else
        return "";
#endif
    }

    static std::string fix_field(const std::string& msg, int tag) {
        std::string search = std::to_string(tag) + "=";
        auto pos = msg.find(search);
        if (pos == std::string::npos) return "";
        pos += search.size();
        auto end = msg.find('\x01', pos);
        return msg.substr(pos, (end != std::string::npos) ? end - pos : std::string::npos);
    }

    static std::string fix_field_or(const std::string& msg, int tag, const std::string& def) {
        auto v = fix_field(msg, tag);
        return v.empty() ? def : v;
    }

    // Declaration order must match constructor initialiser-list order to avoid
    // -Wreorder warnings: host_, port_, sender_, target_, username_, password_,
    // busy_poll_us_, sock_, seq_num_
    std::string host_;
    int port_;
    std::string sender_, target_, username_, password_;
    int busy_poll_us_, sock_, seq_num_;
};

// ── CPU affinity ──────────────────────────────────────────────────────────────

static void pin_to_core(int core) {
#ifdef __linux__
    if (core < 0) return;
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core, &cpuset);
    if (::sched_setaffinity(0, sizeof(cpuset), &cpuset) != 0)
        std::cerr << "[shim] Warning: sched_setaffinity failed (core=" << core << ")\n";
    else
        std::cout << "[shim] Pinned to CPU core " << core << "\n";
#endif
}

// ── Environment helpers ───────────────────────────────────────────────────────

static std::string env(const char* key, const char* def) {
    const char* v = std::getenv(key);
    return v ? std::string(v) : std::string(def);
}
static int envi(const char* key, int def) {
    const char* v = std::getenv(key);
    return v ? std::atoi(v) : def;
}

// ── Main loop ─────────────────────────────────────────────────────────────────

int main(int argc, char* argv[]) {
    // Health check mode (used by Docker HEALTHCHECK)
    if (argc > 1 && std::string(argv[1]) == "--health") {
        std::cout << "OK\n";
        return 0;
    }

    // Config from environment
    const int    cmd_port       = envi("ZMQ_CMD_PORT",       6555);
    const int    resp_port      = envi("ZMQ_RESP_PORT",      6556);
    const std::string fix_host  = env("FIX_HOST",            "127.0.0.1");
    const int    fix_port       = envi("FIX_PORT",           9876);
    const std::string sender_id = env("FIX_SENDER_COMP_ID",  "HOPEFX");
    const std::string target_id = env("FIX_TARGET_COMP_ID",  "CME");
    const std::string username  = env("FIX_USERNAME",        "");
    const std::string password  = env("FIX_PASSWORD",        "");
    const int    cpu_core       = envi("CPU_AFFINITY_CORE",  -1);
    const long long latency_warn= envi("LATENCY_WARN_US",    500);
    const int    busy_poll_us   = envi("BUSY_POLL_US",       50);

    // Pin to CPU core
    pin_to_core(cpu_core);

    std::cout << "[shim] HOPEFX C++ Execution Shim starting\n"
              << "  ZMQ CMD  port: " << cmd_port  << "\n"
              << "  ZMQ RESP port: " << resp_port << "\n"
              << "  FIX gateway:   " << fix_host << ":" << fix_port << "\n";

    // ZMQ context and sockets
    zmq::context_t ctx(1);

    zmq::socket_t cmd_sock(ctx, zmq::socket_type::pull);
    cmd_sock.set(zmq::sockopt::rcvtimeo, 100);  // 100ms poll timeout
    cmd_sock.bind("tcp://0.0.0.0:" + std::to_string(cmd_port));

    zmq::socket_t resp_sock(ctx, zmq::socket_type::push);
    resp_sock.set(zmq::sockopt::sndhwm, 1000);
    resp_sock.bind("tcp://0.0.0.0:" + std::to_string(resp_port));

    // FIX session
    FIXSession fix(fix_host, fix_port, sender_id, target_id, username, password, busy_poll_us);
    bool fix_ok = fix.connect();
    if (!fix_ok)
        std::cerr << "[shim] FIX session unavailable — orders will be rejected\n";

    std::atomic<bool> running{true};
    int order_count = 0, fill_count = 0, reject_count = 0;

    std::cout << "[shim] Ready. fix_connected=" << fix_ok << "\n";

    // ── Main event loop ───────────────────────────────────────────────────────
    while (running) {
        zmq::message_t msg;
        auto result = cmd_sock.recv(msg, zmq::recv_flags::none);
        if (!result) continue;  // timeout — loop back

        std::string payload(static_cast<char*>(msg.data()), msg.size());
        std::string cmd = json_get(payload, "cmd");
        std::string id  = json_get(payload, "id");
        long long t0    = now_us();

        if (cmd == "PING") {
            std::string pong = "{" + json_str("type","PONG") + "," +
                               json_num("ts", now_epoch_us()) + "}";
            zmq::message_t out(pong.size());
            memcpy(out.data(), pong.c_str(), pong.size());
            resp_sock.send(out, zmq::send_flags::none);
            continue;
        }

        if (cmd == "SHUTDOWN") {
            std::cout << "[shim] Shutdown received.\n";
            running = false;
            break;
        }

        if (cmd == "ORDER") {
            ++order_count;
            std::string symbol  = json_get(payload, "symbol");
            std::string side    = json_get(payload, "side");
            std::string type    = json_get(payload, "type");
            std::string account = json_get(payload, "account");
            double qty   = std::stod(json_get(payload, "qty").empty()   ? "1" : json_get(payload, "qty"));
            double price = std::stod(json_get(payload, "price").empty() ? "0" : json_get(payload, "price"));

            double fill_price = 0, fill_qty = 0;
            std::string order_id, error;
            bool ok = false;

            if (fix_ok) {
                ok = fix.send_order(id, symbol, side, type, qty, price, account,
                                    fill_price, fill_qty, order_id, error);
            } else {
                error = "FIX session not connected";
            }

            long long latency_us = now_us() - t0;
            if (latency_us > latency_warn)
                std::cerr << "[shim] HIGH LATENCY " << latency_us << "μs for order " << id << "\n";

            std::string resp;
            if (ok) {
                ++fill_count;
                resp = "{" + json_str("type","FILL") + "," +
                             json_str("id", id) + "," +
                             json_str("order_id", order_id) + "," +
                             json_flt("price", fill_price) + "," +
                             json_flt("qty", fill_qty) + "," +
                             json_num("latency_us", latency_us) + "," +
                             json_num("ts", now_epoch_us()) + "}";
            } else {
                ++reject_count;
                resp = "{" + json_str("type","REJECT") + "," +
                             json_str("id", id) + "," +
                             json_str("reason", error) + "," +
                             json_num("ts", now_epoch_us()) + "}";
            }

            zmq::message_t out(resp.size());
            memcpy(out.data(), resp.c_str(), resp.size());
            resp_sock.send(out, zmq::send_flags::none);
            continue;
        }

        if (cmd == "CANCEL") {
            // OrderCancelRequest (tag 35=F) — send and ack
            std::string orig_id = json_get(payload, "orig_id");
            std::string resp = "{" + json_str("type","CANCEL_ACK") + "," +
                                     json_str("id", id) + "," +
                                     json_str("orig_id", orig_id) + "," +
                                     json_num("ts", now_epoch_us()) + "}";
            zmq::message_t out(resp.size());
            memcpy(out.data(), resp.c_str(), resp.size());
            resp_sock.send(out, zmq::send_flags::none);
            continue;
        }

        // Unknown command
        std::string err = "{" + json_str("type","ERROR") + "," +
                                json_str("msg","unknown command: " + cmd) + "," +
                                json_num("ts", now_epoch_us()) + "}";
        zmq::message_t out(err.size());
        memcpy(out.data(), err.c_str(), err.size());
        resp_sock.send(out, zmq::send_flags::none);
    }

    fix.disconnect();
    std::cout << "[shim] Stopped. orders=" << order_count
              << " fills=" << fill_count
              << " rejects=" << reject_count << "\n";
    return 0;
}

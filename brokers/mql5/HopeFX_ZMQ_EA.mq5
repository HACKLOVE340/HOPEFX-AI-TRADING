//+------------------------------------------------------------------+
//| HopeFX_ZMQ_EA.mq5                                                |
//| HopeFX AI Trading — ZeroMQ Expert Advisor                        |
//| Copyright (c) 2025-2026 HopeFX                                   |
//| AGPL-3.0 — see LICENSE                                           |
//+------------------------------------------------------------------+
//
// PURPOSE
// -------
// Companion EA for brokers/mt5_zmq_bridge.py.
// Receives order/close/modify commands from the Python bridge via ZMQ PULL,
// executes them in MT5, and sends fill confirmations + live ticks back via
// ZMQ PUSH.
//
// PROTOCOL (JSON over ZMQ)
// ------------------------
// Receive (PULL from Python):
//   {"cmd":"ORDER",  "id":"<uuid>", "symbol":"XAUUSD", "side":"BUY",
//    "lots":0.01, "sl":1900.0, "tp":1950.0, "comment":"hopefx"}
//   {"cmd":"CLOSE",  "id":"<uuid>", "ticket":12345678}
//   {"cmd":"MODIFY", "id":"<uuid>", "ticket":12345678, "sl":1905.0, "tp":1955.0}
//   {"cmd":"PING",   "id":"<uuid>"}
//
// Send (PUSH to Python):
//   {"type":"FILL",  "id":"<uuid>", "ticket":12345678, "symbol":"XAUUSD",
//    "side":"BUY", "lots":0.01, "price":1920.5, "ts":1711234567890}
//   {"type":"TICK",  "symbol":"XAUUSD", "bid":1920.4, "ask":1920.6,
//    "ts":1711234567890}
//   {"type":"ERROR", "id":"<uuid>", "code":10006, "msg":"Trade disabled"}
//   {"type":"PONG",  "id":"<uuid>", "ts":1711234567890}
//
// DEPENDENCIES
// ------------
// Requires mql5-zmq library (https://github.com/dingmaotu/mql5-zmq).
// Copy ZmqContext.mqh, ZmqSocket.mqh into MQL5/Include/Zmq/.
//
// INPUTS
// ------
// PythonCmdPort  — port Python PUSHes commands on  (default 5555)
// PythonRespPort — port Python PULLs responses on  (default 5556)
// PythonHost     — Python host IP                  (default "127.0.0.1")
// TickSymbol     — symbol to stream ticks for      (default current chart)
// MaxLotsPerOrder— safety cap on lot size          (default 1.0)
// EnableTrading  — master kill switch              (default true)
//+------------------------------------------------------------------+

#property copyright "HopeFX AI Trading"
#property version   "1.00"
#property strict

#include <Zmq/ZmqContext.mqh>
#include <Zmq/ZmqSocket.mqh>

//── Inputs ────────────────────────────────────────────────────────────────────
input int    PythonCmdPort   = 5555;
input int    PythonRespPort  = 5556;
input string PythonHost      = "127.0.0.1";
input string TickSymbol      = "";          // empty = current chart symbol
input double MaxLotsPerOrder = 1.0;
input bool   EnableTrading   = true;

//── Globals ───────────────────────────────────────────────────────────────────
ZmqContext g_ctx;
ZmqSocket  g_pull(g_ctx, ZMQ_PULL);   // receive commands from Python
ZmqSocket  g_push(g_ctx, ZMQ_PUSH);   // send fills/ticks to Python

string g_tick_symbol;
datetime g_last_tick_ts = 0;

//+------------------------------------------------------------------+
//| Expert initialisation                                             |
//+------------------------------------------------------------------+
int OnInit()
{
   g_tick_symbol = (TickSymbol == "") ? Symbol() : TickSymbol;

   // Connect PULL to Python PUSH port
   string pull_addr = StringFormat("tcp://%s:%d", PythonHost, PythonCmdPort);
   if (!g_pull.connect(pull_addr))
   {
      Print("HopeFX ZMQ EA: PULL connect failed — ", pull_addr);
      return INIT_FAILED;
   }
   g_pull.setReceiveHighWaterMark(1000);
   g_pull.setLinger(0);

   // Connect PUSH to Python PULL port
   string push_addr = StringFormat("tcp://%s:%d", PythonHost, PythonRespPort);
   if (!g_push.connect(push_addr))
   {
      Print("HopeFX ZMQ EA: PUSH connect failed — ", push_addr);
      return INIT_FAILED;
   }
   g_push.setSendHighWaterMark(1000);
   g_push.setLinger(0);

   Print("HopeFX ZMQ EA initialised — cmd=", pull_addr, " resp=", push_addr);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization                                           |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   g_pull.disconnect(StringFormat("tcp://%s:%d", PythonHost, PythonCmdPort));
   g_push.disconnect(StringFormat("tcp://%s:%d", PythonHost, PythonRespPort));
   Print("HopeFX ZMQ EA stopped (reason=", reason, ")");
}

//+------------------------------------------------------------------+
//| Expert tick — poll for commands + stream ticks                    |
//+------------------------------------------------------------------+
void OnTick()
{
   // ── Stream tick to Python ────────────────────────────────────────
   MqlTick tick;
   if (SymbolInfoTick(g_tick_symbol, tick))
   {
      datetime ts_ms = (datetime)(tick.time * 1000 + tick.time_msc);
      if (ts_ms != g_last_tick_ts)
      {
         g_last_tick_ts = ts_ms;
         string tick_msg = StringFormat(
            "{\"type\":\"TICK\",\"symbol\":\"%s\",\"bid\":%.5f,\"ask\":%.5f,\"ts\":%I64d}",
            g_tick_symbol, tick.bid, tick.ask, (long)ts_ms
         );
         ZmqMsg tick_zmq(tick_msg);
         g_push.send(tick_zmq, true);  // non-blocking
      }
   }

   // ── Poll for commands (non-blocking) ────────────────────────────
   ZmqMsg cmd_msg;
   while (g_pull.recv(cmd_msg, true))  // true = non-blocking
   {
      string raw = cmd_msg.getData();
      if (StringLen(raw) == 0) break;
      ProcessCommand(raw);
   }
}

//+------------------------------------------------------------------+
//| Parse and execute a JSON command from Python                      |
//+------------------------------------------------------------------+
void ProcessCommand(const string &raw)
{
   // Minimal JSON parser — extract key fields by string search.
   // For production, replace with a proper MQL5 JSON library.
   string cmd  = JsonGetString(raw, "cmd");
   string id   = JsonGetString(raw, "id");

   if (cmd == "PING")
   {
      long ts_ms = (long)(TimeCurrent() * 1000);
      string pong = StringFormat(
         "{\"type\":\"PONG\",\"id\":\"%s\",\"ts\":%I64d}", id, ts_ms
      );
      ZmqMsg pong_msg(pong);
      g_push.send(pong_msg, false);
      return;
   }

   if (cmd == "ORDER")
   {
      if (!EnableTrading)
      {
         SendError(id, 10027, "Trading disabled by EA input");
         return;
      }
      string symbol = JsonGetString(raw, "symbol");
      string side   = JsonGetString(raw, "side");
      double lots   = JsonGetDouble(raw, "lots");
      double sl     = JsonGetDouble(raw, "sl");
      double tp     = JsonGetDouble(raw, "tp");
      string comment = JsonGetString(raw, "comment");

      if (lots > MaxLotsPerOrder)
      {
         SendError(id, 10013, StringFormat("Lots %.2f exceeds MaxLotsPerOrder %.2f", lots, MaxLotsPerOrder));
         return;
      }

      ExecuteOrder(id, symbol, side, lots, sl, tp, comment);
      return;
   }

   if (cmd == "CLOSE")
   {
      long ticket = JsonGetLong(raw, "ticket");
      double lots = JsonGetDouble(raw, "lots");
      ClosePosition(id, ticket, lots);
      return;
   }

   if (cmd == "MODIFY")
   {
      long ticket = JsonGetLong(raw, "ticket");
      double sl   = JsonGetDouble(raw, "sl");
      double tp   = JsonGetDouble(raw, "tp");
      ModifyPosition(id, ticket, sl, tp);
      return;
   }

   Print("HopeFX ZMQ EA: unknown command '", cmd, "'");
}

//+------------------------------------------------------------------+
//| Execute a market order                                            |
//+------------------------------------------------------------------+
void ExecuteOrder(
   const string &id,
   const string &symbol,
   const string &side,
   double lots,
   double sl,
   double tp,
   const string &comment
)
{
   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = symbol;
   req.volume    = lots;
   req.type      = (side == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.price     = (side == "BUY")
                   ? SymbolInfoDouble(symbol, SYMBOL_ASK)
                   : SymbolInfoDouble(symbol, SYMBOL_BID);
   req.sl        = sl;
   req.tp        = tp;
   req.deviation = 10;
   req.magic     = 20260101;
   req.comment   = comment;
   req.type_filling = ORDER_FILLING_IOC;

   if (!OrderSend(req, res))
   {
      SendError(id, (int)res.retcode, res.comment);
      return;
   }

   long ts_ms = (long)(TimeCurrent() * 1000);
   string fill = StringFormat(
      "{\"type\":\"FILL\",\"id\":\"%s\",\"ticket\":%I64d,"
      "\"symbol\":\"%s\",\"side\":\"%s\",\"lots\":%.2f,"
      "\"price\":%.5f,\"ts\":%I64d}",
      id, (long)res.deal, symbol, side, lots, res.price, ts_ms
   );
   ZmqMsg fill_msg(fill);
   g_push.send(fill_msg, false);
   Print("HopeFX ZMQ EA: ORDER filled ticket=", res.deal, " price=", res.price);
}

//+------------------------------------------------------------------+
//| Close an open position by ticket                                  |
//+------------------------------------------------------------------+
void ClosePosition(const string &id, long ticket, double lots)
{
   if (!PositionSelectByTicket((ulong)ticket))
   {
      SendError(id, 10004, StringFormat("Position %I64d not found", ticket));
      return;
   }

   string symbol = PositionGetString(POSITION_SYMBOL);
   double pos_lots = (lots > 0) ? lots : PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE pos_type = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);

   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   req.action    = TRADE_ACTION_DEAL;
   req.symbol    = symbol;
   req.volume    = pos_lots;
   req.type      = (pos_type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   req.price     = (pos_type == POSITION_TYPE_BUY)
                   ? SymbolInfoDouble(symbol, SYMBOL_BID)
                   : SymbolInfoDouble(symbol, SYMBOL_ASK);
   req.position  = (ulong)ticket;
   req.deviation = 10;
   req.magic     = 20260101;
   req.comment   = "hopefx-close";
   req.type_filling = ORDER_FILLING_IOC;

   if (!OrderSend(req, res))
   {
      SendError(id, (int)res.retcode, res.comment);
      return;
   }

   long ts_ms = (long)(TimeCurrent() * 1000);
   string fill = StringFormat(
      "{\"type\":\"FILL\",\"id\":\"%s\",\"ticket\":%I64d,"
      "\"symbol\":\"%s\",\"side\":\"CLOSE\",\"lots\":%.2f,"
      "\"price\":%.5f,\"ts\":%I64d}",
      id, (long)res.deal, symbol, pos_lots, res.price, ts_ms
   );
   ZmqMsg fill_msg(fill);
   g_push.send(fill_msg, false);
}

//+------------------------------------------------------------------+
//| Modify SL/TP on an open position                                  |
//+------------------------------------------------------------------+
void ModifyPosition(const string &id, long ticket, double sl, double tp)
{
   if (!PositionSelectByTicket((ulong)ticket))
   {
      SendError(id, 10004, StringFormat("Position %I64d not found", ticket));
      return;
   }

   MqlTradeRequest req = {};
   MqlTradeResult  res = {};

   req.action   = TRADE_ACTION_SLTP;
   req.symbol   = PositionGetString(POSITION_SYMBOL);
   req.position = (ulong)ticket;
   req.sl       = sl;
   req.tp       = tp;

   if (!OrderSend(req, res))
   {
      SendError(id, (int)res.retcode, res.comment);
      return;
   }

   long ts_ms = (long)(TimeCurrent() * 1000);
   string fill = StringFormat(
      "{\"type\":\"FILL\",\"id\":\"%s\",\"ticket\":%I64d,"
      "\"symbol\":\"%s\",\"side\":\"MODIFY\",\"lots\":0,"
      "\"price\":0,\"ts\":%I64d}",
      id, ticket, req.symbol, ts_ms
   );
   ZmqMsg fill_msg(fill);
   g_push.send(fill_msg, false);
}

//+------------------------------------------------------------------+
//| Send an error response to Python                                  |
//+------------------------------------------------------------------+
void SendError(const string &id, int code, const string &msg)
{
   string err = StringFormat(
      "{\"type\":\"ERROR\",\"id\":\"%s\",\"code\":%d,\"msg\":\"%s\"}",
      id, code, msg
   );
   ZmqMsg err_msg(err);
   g_push.send(err_msg, false);
   Print("HopeFX ZMQ EA: ERROR id=", id, " code=", code, " msg=", msg);
}

//+------------------------------------------------------------------+
//| Minimal JSON string field extractor                               |
//+------------------------------------------------------------------+
string JsonGetString(const string &json, const string &key)
{
   string search = "\"" + key + "\":\"";
   int pos = StringFind(json, search);
   if (pos < 0) return "";
   pos += StringLen(search);
   int end = StringFind(json, "\"", pos);
   if (end < 0) return "";
   return StringSubstr(json, pos, end - pos);
}

double JsonGetDouble(const string &json, const string &key)
{
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if (pos < 0) return 0.0;
   pos += StringLen(search);
   // Read until comma, } or end
   string val = "";
   for (int i = pos; i < StringLen(json); i++)
   {
      ushort c = StringGetCharacter(json, i);
      if (c == ',' || c == '}' || c == ' ') break;
      val += ShortToString(c);
   }
   return StringToDouble(val);
}

long JsonGetLong(const string &json, const string &key)
{
   return (long)JsonGetDouble(json, key);
}
//+------------------------------------------------------------------+

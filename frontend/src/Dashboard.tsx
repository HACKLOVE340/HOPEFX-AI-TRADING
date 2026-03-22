import React, { useEffect, useState } from 'react';
import { Line } from 'react-chartjs-2';

const Dashboard = () => {
  const [data, setData] = useState({ labels: [], datasets: [] });

  useEffect(() => {
    const ws = new WebSocket('wss://your-websocket-url');

    ws.onmessage = (event) => {
      const newData = JSON.parse(event.data);
      setData((prevData) => ({
        labels: [...prevData.labels, newData.label],
        datasets: [{
          ...prevData.datasets[0],
          data: [...prevData.datasets[0].data, newData.value],
        }],
      }));
    };

    return () => { ws.close(); };
  }, []);

  return (
    <div>
      <h2>Real-Time Chart</h2>
      <Line data={data} />
    </div>
  );
};

export default Dashboard;

import { useEffect, useRef } from 'react'
import { createChart, IChartApi, ISeriesApi, AreaData } from 'lightweight-charts'

export function EquityChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { color: 'transparent' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: {
        borderColor: '#334155',
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#f59e0b',
          labelBackgroundColor: '#f59e0b',
        },
        horzLine: {
          color: '#f59e0b',
          labelBackgroundColor: '#f59e0b',
        },
      },
    })

    const series = chart.addAreaSeries({
      lineColor: '#f59e0b',
      topColor: 'rgba(245, 158, 11, 0.4)',
      bottomColor: 'rgba(245, 158, 11, 0.0)',
      lineWidth: 2,
    })

    // Generate sample equity curve
    const data: AreaData[] = []
    let value = 100000
    const now = Date.now() / 1000
    
    for (let i = 100; i >= 0; i--) {
      value = value * (1 + (Math.random() - 0.48) * 0.02)
      data.push({
        time: now - i * 86400 as any,
        value: value,
      })
    }

    series.setData(data)
    chart.timeScale().fitContent()

    chartRef.current = chart

    const handleResize = () => {
      chart.applyOptions({ width: containerRef.current?.clientWidth })
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [])

  return <div ref={containerRef} className="h-[300px]" />
}

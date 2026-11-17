import {
  AreaSeries,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type ISeriesApi,
  type SeriesMarker,
  type SeriesType,
  type Time,
} from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import type { BarPoint, IndicatorResult } from '../types'
import { fmtCompact, fmtDate, fmtNumber } from '../format'
import {
  indexFromLogical,
  keyboardSelection,
  orderedRange,
  rangeForSessions,
  sessionsForRange,
  type IndexRange,
  type SessionSelection,
} from './chartSelection'

const PALETTE = ['#4cc9f0', '#f4a261', '#b5a642', '#9d8df1', '#5dd39e', '#ef6f6c']

interface ChartProps {
  bars: BarPoint[]
  indexPoints?: Array<{ time: string; value: number }>
  indicators: IndicatorResult[]
  chartType: 'candlestick' | 'line' | 'area'
  theme: 'dark' | 'light'
  height?: number
  actions?: Array<Record<string, unknown>>
  viewLabel: string
  /** "Explain This Move" selection mode. Off by default, so normal chart scrolling is untouched. */
  selectionEnabled?: boolean
  /** The committed interval, kept in sync with date inputs elsewhere on the page. */
  selection?: SessionSelection | null
  /** Called when a drag or keyboard action commits or clears a selection. */
  onSelect?: (selection: SessionSelection | null) => void
}

function toTime(value: string | Time): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number') return new Date(value * 1000).toISOString().slice(0, 10)
  const { year, month, day } = value
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

export default function Chart({
  bars,
  indexPoints = [],
  indicators,
  chartType,
  theme,
  height = 380,
  actions = [],
  viewLabel,
  selectionEnabled = false,
  selection = null,
  onSelect,
}: ChartProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<{ date: string; open?: number; high?: number; low?: number; close: number } | null>(null)
  const selectionRef = useRef<SessionSelection | null>(selection)
  const onSelectRef = useRef<ChartProps['onSelect']>(onSelect)
  const redrawSelectionRef = useRef<(() => void) | null>(null)

  useEffect(() => {
    selectionRef.current = selection
    redrawSelectionRef.current?.()
  }, [selection])

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    host.innerHTML = ''
    const dark = theme === 'dark'
    const colors = {
      background: dark ? '#0d1117' : '#ffffff',
      text: dark ? '#8b949e' : '#57606a',
      grid: dark ? 'rgba(139,148,158,0.12)' : 'rgba(87,96,106,0.12)',
      up: '#3fb950',
      down: '#f85149',
      accent: '#4cc9f0',
      volumeUp: 'rgba(63,185,80,0.35)',
      volumeDown: 'rgba(248,81,73,0.35)',
    }
    const common = {
      layout: {
        background: { type: ColorType.Solid as const, color: colors.background },
        textColor: colors.text,
        fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
        fontSize: 11,
      },
      grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: colors.accent, width: 1 as const, style: LineStyle.Dotted, labelBackgroundColor: colors.accent },
        horzLine: { color: colors.accent, width: 1 as const, style: LineStyle.Dotted, labelBackgroundColor: colors.accent },
      },
      rightPriceScale: { borderColor: colors.grid },
      timeScale: { borderColor: colors.grid, timeVisible: false, rightOffset: 4 },
      localization: { locale: 'en-US' },
      autoSize: false,
    }

    const charts: IChartApi[] = []
    const mainEl = document.createElement('div')
    mainEl.style.height = `${height}px`
    mainEl.style.width = '100%'
    host.appendChild(mainEl)
    mainEl.style.position = 'relative'
    const main = createChart(mainEl, { ...common, width: mainEl.clientWidth || 600, height })
    charts.push(main)

    let series: ISeriesApi<SeriesType>
    if (indexPoints.length > 0 || chartType === 'line') {
      const line = main.addSeries(LineSeries, { color: colors.accent, lineWidth: 2, priceLineVisible: false })
      line.setData(
        (indexPoints.length > 0 ? indexPoints : bars.map((bar) => ({ time: bar.date, value: bar.close }))) as never,
      )
      series = line
    } else if (chartType === 'area') {
      const area = main.addSeries(AreaSeries, {
        lineColor: colors.accent,
        topColor: 'rgba(76,201,240,0.28)',
        bottomColor: 'rgba(76,201,240,0.02)',
        lineWidth: 2,
        priceLineVisible: false,
      })
      area.setData(bars.map((bar) => ({ time: bar.date, value: bar.close })) as never)
      series = area
    } else {
      const candles = main.addSeries(CandlestickSeries, {
        upColor: colors.up,
        downColor: colors.down,
        wickUpColor: colors.up,
        wickDownColor: colors.down,
        borderVisible: false,
      })
      candles.setData(
        bars.map((bar) => ({
          time: bar.date,
          open: bar.open,
          high: bar.high,
          low: bar.low,
          close: bar.close,
        })) as never,
      )
      series = candles
    }

    if (bars.length > 0 && indexPoints.length === 0) {
      const volume = main.addSeries(HistogramSeries, {
        priceScaleId: 'volume',
        priceFormat: { type: 'volume' },
        priceLineVisible: false,
        lastValueVisible: false,
      })
      main.priceScale('volume').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
      volume.setData(
        bars.map((bar) => ({
          time: bar.date,
          value: bar.volume ?? 0,
          color: bar.close >= bar.open ? colors.volumeUp : colors.volumeDown,
        })) as never,
      )
    }

    indicators
      .filter((indicator) => indicator.pane === 'overlay')
      .forEach((indicator, indicatorIndex) => {
        indicator.series.forEach((line, lineIndex) => {
          const overlay = main.addSeries(LineSeries, {
            color: PALETTE[(indicatorIndex + lineIndex) % PALETTE.length],
            lineWidth: 1,
            priceLineVisible: false,
            lastValueVisible: false,
            lineStyle: line.role === 'band' ? LineStyle.Dashed : LineStyle.Solid,
          })
          overlay.setData(line.points as never)
        })
      })

    // Corporate-action markers: splits and dividends visible on the price axis.
    const start = bars[0]?.date ?? ''
    const end = bars[bars.length - 1]?.date ?? ''
    const markers: SeriesMarker<Time>[] = actions
      .map((action) => {
        const exDate = String(action.ex_date ?? '')
        if (!exDate || exDate < start || exDate > end) return null
        const type = String(action.action_type ?? '')
        const isSplit = type.includes('split')
        const label = isSplit
          ? `${action.ratio_to ?? ''}:${action.ratio_from ?? ''} split`
          : type.includes('dividend')
            ? `div ${action.cash_amount ?? ''}`
            : type.replace(/_/g, ' ')
        return {
          time: exDate as Time,
          position: isSplit ? 'aboveBar' : 'belowBar',
          color: isSplit ? '#f4a261' : '#9d8df1',
          shape: isSplit ? 'arrowDown' : 'circle',
          text: label,
        } as SeriesMarker<Time>
      })
      .filter((marker): marker is SeriesMarker<Time> => marker !== null)
      .sort((a, b) => String(a.time).localeCompare(String(b.time)))
    if (markers.length > 0) createSeriesMarkers(series, markers)

    // ---------------------------------------------------------------- range selection
    // The overlay only exists in Explain mode. When it is absent the chart keeps its own
    // scroll, crosshair and pinch behaviour, which is why this is conditional rather than a
    // transparent always-on layer.
    const dates = bars.map((bar) => bar.date)
    let stopSelecting: (() => void) | null = null
    if (selectionEnabled && bars.length > 0 && indexPoints.length === 0) {
      const overlay = document.createElement('div')
      overlay.className = 'chart-range-overlay'
      overlay.tabIndex = 0
      overlay.setAttribute('role', 'application')
      overlay.setAttribute(
        'aria-label',
        'Chart range selection. Drag across candles, or use arrow keys; Shift plus arrow extends; Enter confirms; Escape clears.',
      )
      const band = document.createElement('div')
      band.className = 'chart-range-band'
      band.style.display = 'none'
      overlay.appendChild(band)
      mainEl.appendChild(overlay)

      let draft: IndexRange | null = null
      let anchor: number | null = null

      const drawBand = () => {
        const range = draft ?? rangeForSessions(dates, selectionRef.current)
        if (!range) {
          band.style.display = 'none'
          return
        }
        const leftEdge = main.timeScale().logicalToCoordinate(range.from as never)
        const rightEdge = main.timeScale().logicalToCoordinate(range.to as never)
        if (leftEdge == null || rightEdge == null) {
          band.style.display = 'none'
          return
        }
        // A single candle has zero width; show it as a visible 2px band rather than nothing.
        const left = Math.min(leftEdge, rightEdge)
        const width = Math.max(2, Math.abs(rightEdge - leftEdge))
        band.style.display = 'block'
        band.style.left = `${left}px`
        band.style.width = `${width}px`
      }
      redrawSelectionRef.current = drawBand

      const indexAt = (clientX: number): number | null => {
        const rect = overlay.getBoundingClientRect()
        const logical = main.timeScale().coordinateToLogical(clientX - rect.left)
        return indexFromLogical(logical, dates.length)
      }

      const commit = () => {
        if (!draft) return
        const resolved = sessionsForRange(dates, draft)
        draft = null
        overlay.classList.remove('is-selecting')
        drawBand()
        if (resolved) onSelectRef.current?.(resolved)
      }

      const onPointerDown = (event: PointerEvent) => {
        if (event.button !== 0) return
        const index = indexAt(event.clientX)
        if (index === null) return
        anchor = index
        draft = { from: index, to: index }
        overlay.classList.add('is-selecting')
        try {
          overlay.setPointerCapture(event.pointerId)
        } catch {
          /* capture is an optimisation; the drag still works without it */
        }
        drawBand()
        event.preventDefault()
      }

      const onPointerMove = (event: PointerEvent) => {
        if (anchor === null) return
        const index = indexAt(event.clientX)
        if (index === null) return
        draft = orderedRange(anchor, index, dates.length)
        drawBand()
        event.preventDefault()
      }

      const onPointerUp = (event: PointerEvent) => {
        if (anchor === null) return
        anchor = null
        try {
          overlay.releasePointerCapture(event.pointerId)
        } catch {
          /* already released */
        }
        commit()
      }

      const onPointerCancel = () => {
        anchor = null
        draft = null
        overlay.classList.remove('is-selecting')
        drawBand()
      }

      const onKeyDown = (event: KeyboardEvent) => {
        if (event.key === 'Escape') {
          draft = null
          drawBand()
          onSelectRef.current?.(null)
          event.preventDefault()
          return
        }
        if (event.key === 'Enter') {
          commit()
          event.preventDefault()
          return
        }
        if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
          draft = keyboardSelection(
            dates,
            selectionRef.current,
            event.key as 'ArrowLeft' | 'ArrowRight' | 'Home' | 'End',
            event.shiftKey,
          )
          drawBand()
          event.preventDefault()
        }
      }

      overlay.addEventListener('pointerdown', onPointerDown)
      overlay.addEventListener('pointermove', onPointerMove)
      overlay.addEventListener('pointerup', onPointerUp)
      overlay.addEventListener('pointercancel', onPointerCancel)
      overlay.addEventListener('keydown', onKeyDown)
      const onScaleChange = () => drawBand()
      main.timeScale().subscribeVisibleLogicalRangeChange(onScaleChange)

      stopSelecting = () => {
        main.timeScale().unsubscribeVisibleLogicalRangeChange(onScaleChange)
        overlay.removeEventListener('pointerdown', onPointerDown)
        overlay.removeEventListener('pointermove', onPointerMove)
        overlay.removeEventListener('pointerup', onPointerUp)
        overlay.removeEventListener('pointercancel', onPointerCancel)
        overlay.removeEventListener('keydown', onKeyDown)
        redrawSelectionRef.current = null
        overlay.remove()
      }
      drawBand()
    }

    for (const indicator of indicators.filter((item) => item.pane === 'separate').slice(0, 3)) {
      const paneEl = document.createElement('div')
      paneEl.style.height = '120px'
      paneEl.style.width = '100%'
      paneEl.style.marginTop = '4px'
      host.appendChild(paneEl)
      const pane = createChart(paneEl, { ...common, width: paneEl.clientWidth || 600, height: 120 })
      charts.push(pane)
      indicator.series.forEach((line, lineIndex) => {
        const color = PALETTE[(lineIndex + 1) % PALETTE.length]
        if (line.role === 'histogram') {
          const histogram = pane.addSeries(HistogramSeries, { color, priceLineVisible: false })
          histogram.setData(line.points as never)
        } else {
          const paneLine = pane.addSeries(LineSeries, { color, lineWidth: 1, priceLineVisible: false })
          paneLine.setData(line.points as never)
        }
      })
      pane.timeScale().fitContent()
      main.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (range) pane.timeScale().setVisibleLogicalRange(range)
      })
    }

    main.subscribeCrosshairMove((param) => {
      if (!param.time) {
        setHover(null)
        return
      }
      const data = param.seriesData.get(series)
      const date = toTime(param.time)
      if (data && 'close' in data) {
        setHover({ date, open: data.open, high: data.high, low: data.low, close: data.close })
      } else if (data && 'value' in data) {
        setHover({ date, close: data.value })
      }
    })
    main.timeScale().fitContent()

    const observer = new ResizeObserver(() => {
      for (const chart of charts) {
        chart.applyOptions({ width: chart === main ? mainEl.clientWidth : host.clientWidth })
      }
      redrawSelectionRef.current?.()
    })
    observer.observe(host)

    return () => {
      stopSelecting?.()
      observer.disconnect()
      for (const chart of charts) chart.remove()
      host.innerHTML = ''
    }
  }, [bars, indexPoints, indicators, chartType, theme, height, actions, selectionEnabled])

  const last = bars[bars.length - 1]
  const shown = hover ?? (last ? { date: last.date, open: last.open, high: last.high, low: last.low, close: last.close } : null)

  return (
    <div className="chart-block">
      <div className="chart-legend mono small">
        <span className="legend-view">{viewLabel}</span>
        {shown ? (
          <>
            <span>{fmtDate(shown.date)}</span>
            {shown.open !== undefined && <span>O {fmtNumber(shown.open)}</span>}
            {shown.high !== undefined && <span>H {fmtNumber(shown.high)}</span>}
            {shown.low !== undefined && <span>L {fmtNumber(shown.low)}</span>}
            <span>C {fmtNumber(shown.close)}</span>
            {last?.volume != null && <span>V {fmtCompact(last.volume)}</span>}
          </>
        ) : (
          <span className="muted">No observations in this window</span>
        )}
        {indicators.filter((i) => i.pane === 'overlay').length > 0 && (
          <span className="muted">
            overlays: {indicators.filter((i) => i.pane === 'overlay').map((i) => i.key.toUpperCase()).join(', ')}
          </span>
        )}
      </div>
      <div ref={hostRef} className="chart-host" />
      {indicators.some((indicator) => indicator.warnings.length > 0) && (
        <ul className="chart-notes small muted">
          {indicators.flatMap((indicator) =>
            indicator.warnings.map((warning, index) => (
              <li key={`${indicator.key}-${index}`}>
                {indicator.key.toUpperCase()}: {warning}
              </li>
            )),
          )}
        </ul>
      )}
    </div>
  )
}

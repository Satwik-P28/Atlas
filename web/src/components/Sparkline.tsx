export default function Sparkline({
  values,
  width = 120,
  height = 30,
  positive,
}: {
  values: number[]
  width?: number
  height?: number
  positive?: boolean
}) {
  if (!values || values.length < 2) return <span className="muted small">—</span>
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * (width - 2) + 1
      const y = height - 2 - ((value - min) / span) * (height - 4)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
  const rising = positive ?? values[values.length - 1] >= values[0]
  return (
    <svg
      className={`sparkline ${rising ? 'spark-up' : 'spark-down'}`}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`30-session price trend, ${rising ? 'rising' : 'falling'}`}
    >
      <polyline points={points} fill="none" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

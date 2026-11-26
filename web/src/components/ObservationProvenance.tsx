import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../api'
import { Badge } from './ui'

/**
 * Observation provenance inspector.
 *
 * A market observation in Atlas is a specific provider's statement about one security, one
 * venue and one session, at one revision. This panel shows that identity next to the rights
 * and timing metadata, and lets a researcher pin the exact revision, copy the immutable id,
 * inspect the revision chain, compare a conflicting provider, and replay the pin through the
 * equity model. A pin that cannot be resolved is reported as unavailable; the latest quote is
 * never substituted for it.
 */

type Detail = Record<string, any>

const money = (value: unknown) =>
  typeof value === 'number' && Number.isFinite(value)
    ? value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : '—'

const shortId = (value: unknown) => (typeof value === 'string' && value ? value : '—')

export default function ObservationProvenance({
  securityId,
  issuerId,
  asOf,
  replay,
}: {
  securityId?: string
  issuerId?: string
  asOf?: string
  replay?: (pin: Record<string, any>) => Promise<Record<string, any>>
}) {
  const [items, setItems] = useState<Detail[]>([])
  const [detail, setDetail] = useState<Detail | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [pinned, setPinned] = useState<Record<string, any> | null>(null)
  const [replayState, setReplayState] = useState<Record<string, any> | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!securityId) return
    setBusy('list')
    setError(null)
    try {
      const payload = await api.securityObservations(securityId, 60)
      const list = (payload.items ?? []) as Detail[]
      setItems(list)
      if (list.length && !list.some((item) => item.observation_id === selectedId)) {
        setSelectedId(list[0].observation_id)
      }
      if (!list.length) {
        setDetail(null)
        setMessage('No stored market observation exists for this security.')
      }
    } catch (caught) {
      setError((caught as Error).message)
    } finally {
      setBusy(null)
    }
  }, [securityId, selectedId])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!selectedId) return
    let cancelled = false
    setBusy('detail')
    api
      .marketObservation(selectedId)
      .then((payload) => {
        if (!cancelled) {
          setDetail(payload)
          setError(null)
        }
      })
      .catch((caught: unknown) => {
        if (!cancelled) {
          setError(caught instanceof ApiError ? caught.message : String(caught))
          setDetail(null)
        }
      })
      .finally(() => {
        if (!cancelled) setBusy(null)
      })
    return () => {
      cancelled = true
    }
  }, [selectedId])

  const observation = detail?.observation ?? null
  const source = detail?.source ?? null
  const revision = detail?.session ?? null

  const runReplay = useCallback(
    async (pin: Record<string, any> | null, mode: 'reopen' | 'update') => {
      if (!pin) return
      setBusy(mode)
      setError(null)
      try {
        const result = replay
          ? await replay(pin)
          : await api.marketReplay(pin, asOf ?? null)
        setPinned(pin)
        setReplayState({ mode, pin, result })
        setMessage(
          mode === 'reopen'
            ? 'Reopened the analysis from the pinned revision.'
            : 'Updated the analysis to the selected revision as an explicit action.',
        )
      } catch (caught) {
        setReplayState({ mode, pin, error: (caught as Error).message })
        setError((caught as Error).message)
      } finally {
        setBusy(null)
      }
    },
    [replay, asOf],
  )

  const latestRevision = useMemo(() => {
    if (!detail?.revisions?.length) return null
    return [...detail.revisions].sort(
      (left: Detail, right: Detail) => Number(right.revision_seq) - Number(left.revision_seq),
    )[0]
  }, [detail])

  if (!securityId) {
    return (
      <div className="card" data-testid="provenance-panel">
        <h3>Observation provenance</h3>
        <p className="muted small">
          Select a security with stored observations to inspect its immutable market-observation identity.
        </p>
      </div>
    )
  }

  const replayMarket =
    replayState?.result?.valuation?.market ??
    replayState?.result?.market ??
    (replayState?.result?.schema === 'atlas.market_price.replay.v1' ? replayState.result : null)
  const replayValue =
    replayState?.result?.valuation?.institution?.outputs?.value_per_share ??
    replayState?.result?.valuation?.dcf?.outputs?.value_per_share ??
    null
  const replayPrice =
    replayMarket?.status === 'available'
      ? replayMarket.price
      : replayMarket?.price?.close ?? null
  const replayPinStatus = replayMarket?.pin_status ?? replayMarket?.status ?? 'not applicable'

  return (
    <div className="card" data-testid="provenance-panel">
      <div className="section-head">
        <div>
          <div className="eyebrow">Market observation provenance</div>
          <h3>Exact revision, source and rights</h3>
        </div>
        <Badge tone={source?.export_allowed ? 'positive' : 'warn'}>
          {source?.redistribution ?? 'rights unknown'}
        </Badge>
      </div>

      <div className="row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
        <select
          className="mono"
          data-testid="provenance-observation"
          aria-label="Stored observation"
          value={selectedId ?? ''}
          onChange={(event) => setSelectedId(event.target.value)}
          style={{ minWidth: 280 }}
        >
          {items.map((item) => (
            <option key={item.observation_id} value={item.observation_id}>
              {item.session_date} · {item.source_id} · r{item.revision_seq} · {item.close}
            </option>
          ))}
        </select>
        <button className="button secondary" onClick={() => void load()} disabled={busy !== null}>
          Refresh
        </button>
      </div>

      {error && <p className="banner banner-error small" data-testid="provenance-error">{error}</p>}
      {!items.length && !error && (
        <p className="muted small" data-testid="provenance-status">
          {message ?? 'No observations are stored for this security. Atlas does not invent a quote.'}
        </p>
      )}

      {detail && observation && (
        <>
          <div className="table-wrap">
            <table className="data-table" data-testid="provenance-source">
              <tbody>
                <tr>
                  <th>Security / listing</th>
                  <td className="mono">{detail.security?.listing_identity}</td>
                </tr>
                <tr>
                  <th>Issuer</th>
                  <td className="mono">{issuerId ?? '—'}</td>
                </tr>
                <tr>
                  <th>Provider / dataset</th>
                  <td>
                    <span className="mono">{source?.source_id}</span>
                    <div className="muted small">{source?.name} · {source?.kind ?? 'market_data'}</div>
                  </td>
                </tr>
                <tr>
                  <th>Market session</th>
                  <td className="mono">{revision?.session_date} · {revision?.adjustment}</td>
                </tr>
                <tr>
                  <th>Licence</th>
                  <td>{source?.licence ?? 'not recorded'}</td>
                </tr>
                <tr>
                  <th>Redistribution</th>
                  <td>
                    <span className="mono">{source?.redistribution}</span>{' '}
                    <Badge tone={source?.export_allowed ? 'positive' : 'warn'}>
                      export {source?.export_allowed ? 'allowed' : 'withheld'}
                    </Badge>
                  </td>
                </tr>
                <tr>
                  <th>Retrieved / ingested</th>
                  <td className="mono small">{revision?.observed_at} · {revision?.ingested_at}</td>
                </tr>
                <tr>
                  <th>Revision</th>
                  <td className="mono">
                    r{revision?.revision_seq}
                    {revision?.supersedes_seq ? ` (supersedes r${revision.supersedes_seq})` : ''}
                  </td>
                </tr>
                <tr>
                  <th>Observation id</th>
                  <td className="mono" data-testid="provenance-id">{detail.identity?.observation_id}</td>
                </tr>
                <tr>
                  <th>Content hash</th>
                  <td className="mono small" data-testid="provenance-hash" style={{ wordBreak: 'break-all' }}>
                    {detail.identity?.content_hash}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p className="muted small">{detail.caveat}</p>

          <div className="row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <button
              className="button primary"
              data-testid="provenance-pin"
              onClick={() => {
                setPinned(detail.pin)
                setMessage(`Pinned ${detail.identity?.observation_id}.`)
              }}
            >
              Pin this observation
            </button>
            <button
              className="button secondary"
              data-testid="provenance-copy"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(String(detail.identity?.observation_id ?? ''))
                  setMessage(`Copied ${detail.identity?.observation_id}.`)
                } catch {
                  setMessage(`Clipboard unavailable. Identifier: ${detail.identity?.observation_id}`)
                }
              }}
            >
              Copy immutable id
            </button>
            {(
              <button
                className="button secondary"
                data-testid="provenance-replay"
                disabled={busy !== null}
                onClick={() => void runReplay(pinned ?? detail.pin, 'reopen')}
              >
                {busy === 'reopen' ? 'Replaying…' : 'Reopen with this pin'}
              </button>
            )}
            {latestRevision && latestRevision.observation_id !== detail.identity?.observation_id && (
              <button
                className="button secondary"
                data-testid="provenance-update"
                disabled={busy !== null}
                onClick={() => void runReplay(latestRevision.pin ?? { ...detail.pin, revision_seq: latestRevision.revision_seq }, 'update')}
              >
                {busy === 'update' ? 'Updating…' : `Update to r${latestRevision.revision_seq}`}
              </button>
            )}
          </div>

          <div className="card-grid" style={{ marginTop: 12 }}>
            <div className="source-card" data-testid="provenance-revisions">
              <div className="eyebrow">Available revisions</div>
              {(detail.revisions ?? []).map((item: Detail) => (
                <div key={item.observation_id} className="small mono">
                  r{item.revision_seq} · {item.close} · {item.ingested_at}
                  {item.observation_id === observation.observation_id ? ' · shown' : ''}
                </div>
              ))}
              {(detail.revisions ?? []).length <= 1 && (
                <div className="muted small">Only the original revision is stored; no correction has been imported.</div>
              )}
            </div>
            <div className="source-card" data-testid="provenance-conflicts">
              <div className="eyebrow">Provider observations for this session</div>
              {(detail.conflicts ?? []).length === 0 ? (
                <div className="muted small">No competing provider observation is stored for this session.</div>
              ) : (
                (detail.conflicts ?? []).map((item: Detail) => (
                  <div key={item.observation_id} className="small mono">
                    {item.source_id} · {money(item.close)} {item.currency}
                  </div>
                ))
              )}
              <div className="muted small">
                {detail.providers_disagree
                  ? 'Providers disagree for this session; the selected observation is one of several, and switching is explicit.'
                  : 'Any competing observations agree on the close for this session.'}
              </div>
            </div>
          </div>
        </>
      )}

      {(message || pinned) && (
        <p className="small" data-testid="provenance-status">
          {message}
          {pinned && (
            <span className="mono small"> · pinned {shortId(pinned.observation_id)} (r{pinned.revision_seq})</span>
          )}
        </p>
      )}

      {replayState && (
        <div className="card" data-testid="provenance-replay-result">
          <div className="eyebrow">{replayState.mode === 'update' ? 'Explicit revision update' : 'Reopened analysis'}</div>
          {replayState.error ? (
            <p className="small">Replay failed: {replayState.error}</p>
          ) : (
            <p className="small">
              Model value {replayValue === null ? '—' : money(replayValue)}
              {' · '}price {replayPrice === null ? 'unavailable' : money(replayPrice)}
              {' · '}pin status <span className="mono">{replayPinStatus}</span>
              {' · '}exact replay <strong>{replayMarket?.exact_replay ? 'yes' : 'no'}</strong>
            </p>
          )}
          {replayMarket?.status !== 'available' && replayMarket?.reason && (
            <p className="muted small">{replayMarket.reason}</p>
          )}
          {replayMarket && replayMarket.status !== 'available' && (
            <p className="muted small">
              The saved pin is preserved. Reconnect the permitted source that holds this revision, or update
              explicitly to a newer observation; Atlas will not substitute the latest price.
            </p>
          )}
        </div>
      )}

      {asOf && (
        <p className="muted small">
          Information cutoff {asOf}: only sessions at or before the cutoff may be compared, and a pinned session
          after it is reported rather than used as a point-in-time comparison.
        </p>
      )}
    </div>
  )
}

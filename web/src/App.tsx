import { Suspense, lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import AdvancedShell from './shell/AdvancedShell'
import StandardShell from './shell/StandardShell'
import { useSettings } from './state'

// Route-level splitting: opening the Standard desk must not download the quant
// labs, the model studio or the docking engine before the analyst asks for them.
const Markets = lazy(() => import('./pages/Markets'))
const Companies = lazy(() => import('./pages/Companies'))
const Company = lazy(() => import('./pages/Company'))
const Research = lazy(() => import('./pages/Research'))
const EquityResearch = lazy(() => import('./pages/EquityResearch'))
const Screener = lazy(() => import('./pages/Screener'))
const Studio = lazy(() => import('./pages/Studio'))
const Lab = lazy(() => import('./pages/Lab'))
const Institutional = lazy(() => import('./pages/Institutional'))
const Learning = lazy(() => import('./pages/Learning'))
const Economic = lazy(() => import('./pages/Economic'))
const Applications = lazy(() => import('./pages/Applications'))
const Watchlists = lazy(() => import('./pages/Watchlists'))
const Workspaces = lazy(() => import('./pages/Workspaces'))
const WorkspaceView = lazy(() => import('./pages/WorkspaceView'))
const Workstation = lazy(() => import('./pages/Workstation'))
const Filings = lazy(() => import('./pages/Filings'))
const Answers = lazy(() => import('./pages/Answers'))
const Compare = lazy(() => import('./pages/Compare'))
const Data = lazy(() => import('./pages/Data'))

function AtlasRoutes() {
  return (
    <Suspense
      fallback={
        <div className="state-block" role="status">
          Loading view…
        </div>
      }
    >
      <Routes>
        <Route path="/" element={<Markets />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/companies/:identifier" element={<Company />} />
        <Route path="/research" element={<Research />} />
        <Route path="/filings" element={<Filings />} />
        <Route path="/answers" element={<Answers />} />
        <Route path="/compare" element={<Compare />} />
        <Route path="/data" element={<Data />} />
        <Route path="/equity" element={<EquityResearch />} />
        <Route path="/screeners" element={<Screener />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/lab" element={<Lab />} />
        <Route path="/lab/institutional" element={<Institutional />} />
        <Route path="/lab/learning" element={<Learning />} />
        <Route path="/lab/economic" element={<Economic />} />
        <Route path="/applications" element={<Applications />} />
        <Route path="/watchlists" element={<Watchlists />} />
        <Route path="/workspaces" element={<Workspaces />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceView />} />
        <Route path="/workstation" element={<Workstation />} />
        <Route path="/workstation/:workspaceId" element={<Workstation />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Suspense>
  )
}

/** Standard and Advanced share one router, one data layer and one evidence
 * contract. Only the shell differs, so switching modes cannot change a number. */
export default function App() {
  const { mode } = useSettings()
  return mode === 'advanced' ? (
    <AdvancedShell>
      <AtlasRoutes />
    </AdvancedShell>
  ) : (
    <StandardShell>
      <AtlasRoutes />
    </StandardShell>
  )
}

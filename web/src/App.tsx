import { Navigate, Route, Routes } from 'react-router-dom'
import AdvancedShell from './shell/AdvancedShell'
import StandardShell from './shell/StandardShell'
import { useSettings } from './state'
import Applications from './pages/Applications'
import Companies from './pages/Companies'
import Company from './pages/Company'
import Economic from './pages/Economic'
import EquityResearch from './pages/EquityResearch'
import Institutional from './pages/Institutional'
import Lab from './pages/Lab'
import Learning from './pages/Learning'
import Markets from './pages/Markets'
import Research from './pages/Research'
import Screener from './pages/Screener'
import Studio from './pages/Studio'
import Watchlists from './pages/Watchlists'
import WorkspaceView from './pages/WorkspaceView'
import Workspaces from './pages/Workspaces'
import Workstation from './pages/Workstation'

function AtlasRoutes() {
  return (
    <Routes>
      <Route path="/" element={<Markets />} />
      <Route path="/companies" element={<Companies />} />
      <Route path="/companies/:identifier" element={<Company />} />
      <Route path="/research" element={<Research />} />
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

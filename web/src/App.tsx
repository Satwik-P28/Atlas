import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import Applications from './pages/Applications'
import Companies from './pages/Companies'
import Company from './pages/Company'
import Lab from './pages/Lab'
import Institutional from './pages/Institutional'
import Economic from './pages/Economic'
import EquityResearch from './pages/EquityResearch'
import Learning from './pages/Learning'
import Markets from './pages/Markets'
import Research from './pages/Research'
import Screener from './pages/Screener'
import Studio from './pages/Studio'
import Watchlists from './pages/Watchlists'
import WorkspaceView from './pages/WorkspaceView'
import Workspaces from './pages/Workspaces'

export default function App() {
  return (
    <Shell>
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
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}

import { Navigate, Route, Routes } from 'react-router-dom'
import Shell from './components/Shell'
import Companies from './pages/Companies'
import Company from './pages/Company'
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
        <Route path="/screeners" element={<Screener />} />
        <Route path="/studio" element={<Studio />} />
        <Route path="/watchlists" element={<Watchlists />} />
        <Route path="/workspaces" element={<Workspaces />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceView />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Shell>
  )
}

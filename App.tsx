import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import { WeatherProvider } from "./context/WeatherContext";
import { AlertsProvider } from "./context/AlertsContext";
import { AppShell } from "./components/layout/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { MapsPage } from "./pages/MapsPage";
import { ForecastPage } from "./pages/ForecastPage";
import { ChatPage } from "./pages/ChatPage";
import { ComparePage } from "./pages/ComparePage";
import { SavedPage } from "./pages/SavedPage";
import { AlertsPage } from "./pages/AlertsPage";
import { SettingsPage } from "./pages/SettingsPage";

export default function App() {
  return (
    <AppProvider>
      <WeatherProvider>
        <AlertsProvider>
          <BrowserRouter>
            <AppShell>
              <Routes>
                <Route path="/" element={<DashboardPage />} />
                <Route path="/maps" element={<MapsPage />} />
                <Route path="/forecast" element={<ForecastPage />} />
                <Route path="/chat" element={<ChatPage />} />
                <Route path="/compare" element={<ComparePage />} />
                <Route path="/saved" element={<SavedPage />} />
                <Route path="/alerts" element={<AlertsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
                <Route path="*" element={<DashboardPage />} />
              </Routes>
            </AppShell>
          </BrowserRouter>
        </AlertsProvider>
      </WeatherProvider>
    </AppProvider>
  );
}

import { useEffect, useState } from "react";
import Chat from "./components/Chat.jsx";
import LeadPanel from "./components/LeadPanel.jsx";
import ProviderPanel from "./components/ProviderPanel.jsx";
import {
  createSession,
  getHealth,
  getSession,
  searchProviders,
  selectProvider,
  sendMessage,
  setLocation,
  submitContact,
} from "./api.js";

const SESSION_KEY = "home-lead-session-id";
const LOCATION_KEY = "home-lead-location";

function locationFromState(session) {
  if (!session) return "";
  if (session.location_query) return session.location_query;
  return [session.city, session.zip_code].filter(Boolean).join(" ");
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [state, setState] = useState(null);
  const [tab, setTab] = useState("providers");
  const [input, setInput] = useState("");
  const [locationDraft, setLocationDraft] = useState(() => {
    try {
      return localStorage.getItem(LOCATION_KEY) || "";
    } catch {
      return "";
    }
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const healthPayload = await getHealth();
        if (cancelled) return;
        setHealth(healthPayload);
        const saved = localStorage.getItem(SESSION_KEY);
        if (saved) {
          try {
            const restored = await getSession(saved);
            if (cancelled) return;
            adoptSession(restored, { switchTab: true });
            return;
          } catch {
            localStorage.removeItem(SESSION_KEY);
          }
        }
        const created = await createSession();
        if (cancelled) return;
        adoptSession(created.state, { switchTab: true });
      } catch (exc) {
        if (!cancelled) setError(exc.message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  function writeLocationDraft(value) {
    setLocationDraft(value);
    try {
      if (value) localStorage.setItem(LOCATION_KEY, value);
      else localStorage.removeItem(LOCATION_KEY);
    } catch {
      /* ignore quota / private mode */
    }
  }

  function adoptSession(session, { switchTab, keepLocation } = {}) {
    setState(session);
    localStorage.setItem(SESSION_KEY, session.id);
    if (!keepLocation) {
      writeLocationDraft(locationFromState(session));
    }
    if (!switchTab) return;
    if (session.stage === "collecting_contact" || session.stage === "lead_ready") {
      setTab("lead");
    } else {
      setTab("providers");
    }
  }

  function applyTurn(payload) {
    const session = payload.state;
    setState(session);
    localStorage.setItem(SESSION_KEY, session.id);
    const fromServer = locationFromState(session);
    if (fromServer) writeLocationDraft(fromServer);
    if (session.stage === "collecting_contact" || session.stage === "lead_ready") {
      setTab("lead");
    }
    if (session.providers?.length) {
      if (session.stage === "showing_providers" || session.stage === "no_results") {
        setTab("providers");
      }
    }
  }

  async function run(work) {
    setBusy(true);
    setError("");
    try {
      applyTurn(await work());
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  const sessionId = state?.id;

  async function saveLocation() {
    const text = locationDraft.trim();
    if (!sessionId || !text) return;
    await run(() => setLocation(sessionId, text));
  }

  async function startNewLead() {
    setBusy(true);
    setError("");
    const loc = locationDraft.trim();
    try {
      const created = await createSession();
      setInput("");
      adoptSession(created.state, { switchTab: true, keepLocation: Boolean(loc) });
      if (loc) {
        applyTurn(await setLocation(created.state.id, loc));
      }
    } catch (exc) {
      setError(exc.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex h-dvh max-w-7xl flex-col overflow-hidden px-4 py-4">
      <header className="mb-4 flex shrink-0 flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-moss">Lead agent</p>
          <h1 className="display text-3xl text-ink">Home-services lead agent</h1>
          <p className="mt-1 max-w-xl text-sm text-ink/70">
            Set a location, describe the problem, then build a dispatchable lead.
            Emails are drafts only.
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-2">
          <label className="block text-xs font-semibold text-ink/70">
            City or ZIP
            <input
              className="mt-1 w-56 rounded-xl border border-emerald-950/10 bg-white px-3 py-2 text-sm font-normal text-ink outline-none focus:ring-2 focus:ring-moss/30"
              value={locationDraft}
              placeholder="Austin, TX or 78704"
              onChange={(event) => writeLocationDraft(event.target.value)}
              onBlur={() => {
                if (locationDraft.trim() && sessionId) saveLocation();
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  saveLocation();
                }
              }}
            />
          </label>
          <button
            type="button"
            onClick={startNewLead}
            disabled={busy}
            className="rounded-xl bg-white px-4 py-2 text-sm font-semibold text-ink ring-1 ring-emerald-950/10 hover:bg-emerald-50 disabled:opacity-50"
          >
            New lead
          </button>
          <div className="rounded-2xl bg-white/80 px-4 py-2 text-xs text-ink/70 ring-1 ring-emerald-950/10">
            <div>Model: {health?.model || "…"}</div>
            <div>LLM: {health?.deepseek_configured ? "configured" : "missing key"}</div>
            <div>Places: {health?.search_mode || "…"}</div>
          </div>
        </div>
      </header>

      {error && (
        <p className="mb-3 rounded-2xl bg-red-50 px-4 py-2 text-sm text-red-900">{error}</p>
      )}

      <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-2">
        <div className="flex min-h-0 flex-col overflow-hidden rounded-[28px] bg-white/40 p-4 shadow-sm ring-1 ring-emerald-950/10 backdrop-blur">
          {state ? (
            <Chat
              messages={state.messages}
              stage={state.stage}
              safetyAdvice={state.safety_advice}
              input={input}
              setInput={setInput}
              busy={busy}
              analysis={state.analysis}
              onSend={() => {
                const text = input.trim();
                if (!text || !sessionId) return;
                const loc = locationDraft.trim();
                setInput("");
                run(async () => {
                  if (loc) {
                    await setLocation(sessionId, loc);
                  }
                  return sendMessage(sessionId, text);
                });
              }}
            />
          ) : (
            <p className="p-6 text-sm text-ink/60">Starting session…</p>
          )}
        </div>

        <div className="flex min-h-0 flex-col overflow-hidden rounded-[28px] bg-white/40 p-4 shadow-sm ring-1 ring-emerald-950/10 backdrop-blur">
          <div className="mb-3 flex shrink-0 gap-2">
            <TabButton active={tab === "providers"} onClick={() => setTab("providers")}>
              Providers
            </TabButton>
            <TabButton active={tab === "lead"} onClick={() => setTab("lead")}>
              Lead
            </TabButton>
          </div>
          {tab === "providers" ? (
            <div className="min-h-0 flex-1 overflow-hidden">
              <ProviderPanel
                key={sessionId || "providers"}
                providers={state?.providers || []}
                selectedPlaceId={state?.selected_place_id}
                searchSource={state?.search_source}
                searchError={state?.search_error}
                busy={busy}
                onSearch={(category) => {
                  if (!sessionId) return;
                  const loc = locationDraft.trim();
                  if (!loc) {
                    setError("Enter a city or ZIP in the location field at the top first.");
                    return;
                  }
                  run(() => searchProviders(sessionId, category, loc));
                }}
                onSelect={(placeId) => {
                  if (!sessionId) return;
                  run(() => selectProvider(sessionId, placeId));
                }}
              />
            </div>
          ) : (
            <div className="min-h-0 flex-1 overflow-hidden">
              <LeadPanel
                key={sessionId || "lead"}
                lead={state?.lead}
                email={state?.email}
                busy={busy}
                safetyEscalated={state?.stage === "safety_escalated"}
                onContact={(contact) => {
                  if (!sessionId) return;
                  run(() => submitContact(sessionId, contact));
                }}
              />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function TabButton({ active, onClick, children }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full px-4 py-1.5 text-sm font-semibold ${
        active ? "bg-moss text-white" : "bg-white text-ink/70 ring-1 ring-emerald-950/10"
      }`}
    >
      {children}
    </button>
  );
}

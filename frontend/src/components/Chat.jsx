import { useEffect, useRef } from "react";

const STAGE_LABEL = {
  gathering: "Gathering details",
  need_location: "Need location",
  searching: "Searching listings",
  showing_providers: "Providers found",
  no_results: "No listings",
  collecting_contact: "Contact + consent",
  lead_ready: "Lead ready",
  safety_escalated: "Safety hold",
};

export default function Chat({
  messages,
  stage,
  safetyAdvice,
  input,
  setInput,
  onSend,
  busy,
  analysis,
}) {
  const logRef = useRef(null);

  useEffect(() => {
    const node = logRef.current;
    if (node) {
      node.scrollTop = node.scrollHeight;
    }
  }, [messages, busy]);

  return (
    <section className="flex h-full min-h-0 flex-col">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-white/80 px-3 py-1 text-xs font-semibold tracking-wide text-moss-dark ring-1 ring-emerald-900/10">
          {STAGE_LABEL[stage] || stage}
        </span>
        {analysis?.service_category && analysis.service_category !== "unknown" && (
          <span className="rounded-full bg-emerald-50 px-3 py-1 text-xs text-emerald-900 ring-1 ring-emerald-200">
            {analysis.service_category.replaceAll("_", " ")}
            {typeof analysis.category_confidence === "number"
              ? ` · ${Math.round(analysis.category_confidence * 100)}%`
              : ""}
          </span>
        )}
        {analysis?.urgency && (
          <span className="rounded-full bg-amber-50 px-3 py-1 text-xs text-amber-900 ring-1 ring-amber-200">
            {analysis.urgency.replaceAll("_", " ")}
          </span>
        )}
      </div>

      {safetyAdvice && (
        <div className="mb-3 rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-950">
          <p className="font-semibold">Safety first</p>
          {stage === "safety_escalated" ? (
            <p className="mt-1 leading-relaxed">
              Contractor search is paused until you confirm everyone is safe. Follow the
              message in chat, and call 911 if this is an emergency.
            </p>
          ) : (
            <p className="mt-1 leading-relaxed">{safetyAdvice}</p>
          )}
        </div>
      )}

      <div
        ref={logRef}
        className="min-h-0 flex-1 space-y-3 overflow-y-auto rounded-3xl bg-white/55 p-4 ring-1 ring-emerald-950/10"
      >
        {messages.map((message, index) => {
          const isUser = message.role === "user";
          return (
            <div key={`${message.role}-${index}`} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-sm ${
                  isUser
                    ? "bg-moss text-white"
                    : "bg-white text-ink ring-1 ring-emerald-950/8"
                }`}
              >
                {message.content}
              </div>
            </div>
          );
        })}
      </div>

      <form
        className="mt-3 flex shrink-0 gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          onSend();
        }}
      >
        <input
          className="min-w-0 flex-1 rounded-2xl border border-emerald-950/10 bg-white px-4 py-3 text-sm outline-none ring-moss/0 transition focus:ring-2 focus:ring-moss/30"
          placeholder="Describe the problem or add a detail..."
          value={input}
          onChange={(event) => setInput(event.target.value)}
          disabled={busy}
        />
        <button
          type="submit"
          disabled={busy || !input.trim()}
          className="rounded-2xl bg-moss px-5 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-moss-dark disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? "..." : "Send"}
        </button>
      </form>
    </section>
  );
}

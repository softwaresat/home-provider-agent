import { useState } from "react";
import ContactForm from "./ContactForm.jsx";

const STATUS_STYLES = {
  complete: "bg-emerald-100 text-emerald-950",
  incomplete: "bg-amber-100 text-amber-950",
  safety_escalated: "bg-red-100 text-red-950",
};

export default function LeadPanel({
  lead,
  email,
  onContact,
  busy,
  safetyEscalated,
}) {
  const [showJson, setShowJson] = useState(false);
  const [copied, setCopied] = useState(false);
  const status = lead?.status || "incomplete";

  async function copyEmail() {
    if (!email) return;
    const text = `Subject: ${email.subject}\n\n${email.body}`;
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-4 overflow-y-auto pr-1">
      <div className="flex items-center justify-between">
        <span className={`rounded-full px-3 py-1 text-xs font-semibold ${STATUS_STYLES[status]}`}>
          Lead {status.replaceAll("_", " ")}
        </span>
        <button
          type="button"
          className="text-xs font-semibold text-moss underline"
          onClick={() => setShowJson((value) => !value)}
        >
          {showJson ? "Hide JSON" : "Show JSON"}
        </button>
      </div>

      {lead ? (
        <dl className="grid grid-cols-1 gap-2 text-sm">
          <Field label="Summary" value={lead.problem_summary} missing={lead.missing_required?.includes("problem_summary")} />
          <Field label="Category" value={lead.service_category?.replaceAll("_", " ")} missing={lead.missing_required?.includes("service_category")} />
          <Field label="Urgency" value={lead.urgency?.replaceAll("_", " ")} />
          <Field
            label="Location"
            value={[lead.city, lead.zip_code].filter(Boolean).join(", ")}
            missing={lead.missing_required?.includes("city_or_zip")}
          />
          <Field
            label="Service address"
            value={lead.service_address}
            missing={lead.missing_required?.includes("service_address")}
          />
          <Field label="Name" value={lead.customer_name} missing={lead.missing_required?.includes("customer_name")} />
          <Field
            label="Contact"
            value={[lead.customer_phone, lead.customer_email].filter(Boolean).join(" · ")}
            missing={lead.missing_required?.includes("customer_phone_or_email")}
          />
          <Field
            label="Provider"
            value={
              lead.missing_required?.includes("provider_trade_match")
                ? `${lead.selected_provider?.name || "Selected listing"} (trade unconfirmed)`
                : lead.missing_required?.includes("provider_contact")
                  ? `${lead.selected_provider?.name || "Selected listing"} (not contactable)`
                  : lead.selected_provider?.name
            }
            missing={
              lead.missing_required?.includes("selected_provider") ||
              lead.missing_required?.includes("provider_trade_match") ||
              lead.missing_required?.includes("provider_contact")
            }
          />
          <Field
            label="Consent"
            value={lead.consent_to_share ? "Yes" : "No"}
            missing={lead.missing_required?.includes("consent_to_share")}
          />
        </dl>
      ) : (
        <p className="text-sm text-ink/70">No lead yet. Finish the conversation and select a provider.</p>
      )}

      {lead?.provider_match_explanation && (
        <p className="rounded-2xl bg-emerald-50 px-3 py-2 text-xs leading-relaxed text-emerald-950">
          {lead.provider_match_explanation}
        </p>
      )}
      {lead?.verification_note && (
        <p className="text-[11px] leading-relaxed text-ink/50">{lead.verification_note}</p>
      )}

      {showJson && lead && (
        <pre className="overflow-x-auto rounded-2xl bg-ink p-3 text-[11px] text-emerald-50">
          {JSON.stringify(lead, null, 2)}
        </pre>
      )}

      {email && (
        <div className="rounded-2xl bg-white p-4 ring-1 ring-emerald-950/10">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-sm font-semibold">Draft email (not sent)</h3>
            <div className="flex flex-wrap items-center gap-2">
              {email.mailto_url ? (
                <a
                  href={email.mailto_url}
                  className="rounded-lg bg-moss px-3 py-1.5 text-xs font-semibold text-white hover:bg-moss-dark"
                >
                  Open in email client
                </a>
              ) : (
                <button
                  type="button"
                  disabled
                  title="Draft is not ready yet"
                  className="rounded-lg bg-emerald-950/10 px-3 py-1.5 text-xs font-semibold text-ink/40"
                >
                  Open in email client
                </button>
              )}
              {email.fallback_url && (
                <a
                  href={email.fallback_url}
                  target={email.fallback_url.startsWith("http") ? "_blank" : undefined}
                  rel={email.fallback_url.startsWith("http") ? "noreferrer" : undefined}
                  className="rounded-lg bg-white px-3 py-1.5 text-xs font-semibold text-ink ring-1 ring-emerald-950/10 hover:bg-emerald-50"
                >
                  {email.fallback_label || "Open listing"}
                </a>
              )}
              <button type="button" className="text-xs font-semibold text-moss underline" onClick={copyEmail}>
                {copied ? "Copied" : "Copy"}
              </button>
            </div>
          </div>
          <p className="text-xs text-ink/60">
            To: {email.to_email || "your mail app (listing has no email)"} · {email.to_name}
            {email.to_contact ? ` · ${email.to_contact}` : ""}
          </p>
          <p className="mt-1 text-sm font-semibold">{email.subject}</p>
          <pre className="mt-2 whitespace-pre-wrap font-sans text-sm leading-relaxed text-ink/80">{email.body}</pre>
        </div>
      )}

      <div className="rounded-2xl bg-white p-4 ring-1 ring-emerald-950/10">
        <h3 className="mb-3 text-sm font-semibold">Contact and consent</h3>
        <ContactForm
          onSubmit={onContact}
          busy={busy}
          disabledReason={
            safetyEscalated
              ? "Safety-escalated sessions do not produce a dispatchable lead."
              : undefined
          }
        />
      </div>
    </div>
  );
}

function Field({ label, value, missing }) {
  return (
    <div className={`rounded-xl px-3 py-2 ${missing ? "bg-amber-50 ring-1 ring-amber-200" : "bg-white/80"}`}>
      <dt className="text-[11px] font-semibold uppercase tracking-wide text-ink/50">{label}</dt>
      <dd className="text-sm">{value || (missing ? "Missing" : "—")}</dd>
    </div>
  );
}

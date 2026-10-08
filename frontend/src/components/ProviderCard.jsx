function StatusPill({ children, ok }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
        ok ? "bg-emerald-100 text-emerald-900" : "bg-amber-100 text-amber-950"
      }`}
    >
      {children}
    </span>
  );
}

export default function ProviderCard({ provider, selected, onSelect }) {
  const fallback = provider.source === "fallback_fixture";
  const tradeOk = Boolean(provider.trade_confirmed);
  const contactOk = Boolean(provider.contactable || provider.phone || provider.website);
  return (
    <article className={`rounded-2xl border bg-white p-4 shadow-sm ${selected ? "border-moss ring-2 ring-moss/20" : "border-emerald-950/10"}`}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-ink">{provider.name}</h3>
          <p className="mt-1 text-xs text-emerald-900/70">
            {provider.primary_type_display || provider.primary_type || "Type not listed"}
          </p>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${fallback ? "bg-amber-100 text-amber-900" : "bg-emerald-100 text-emerald-900"}`}>
          {fallback ? "Fallback data" : "Listed business"}
        </span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        <StatusPill ok={tradeOk}>{tradeOk ? "Relevant match" : "Trade unconfirmed"}</StatusPill>
        <StatusPill ok={contactOk}>{contactOk ? "Contactable" : "No phone or website"}</StatusPill>
        <StatusPill ok={false}>Availability unconfirmed</StatusPill>
      </div>

      {provider.address ? (
        <p className="mt-2 text-sm text-ink/80">{provider.address}</p>
      ) : (
        <p className="mt-2 text-sm italic text-ink/60">
          {provider.is_service_area_business
            ? "Service-area business — no public address (area not confirmed)"
            : "No public address on the listing"}
        </p>
      )}

      <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink/70">
        {provider.rating != null && (
          <span>
            {provider.rating.toFixed(1)} ★ ({provider.review_count || 0} reviews)
          </span>
        )}
        {provider.phone && <span>{provider.phone}</span>}
        <span>Score {provider.match_score}</span>
      </div>

      {provider.match_reasons?.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-ink/70">
          {provider.match_reasons.slice(0, 4).map((reason) => (
            <li key={reason}>{reason}</li>
          ))}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onSelect(provider.place_id)}
          className="rounded-xl bg-moss px-3 py-1.5 text-xs font-semibold text-white hover:bg-moss-dark"
        >
          {selected ? "Selected" : "Select"}
        </button>
        {provider.maps_url && (
          <a
            className="text-xs font-semibold text-moss underline"
            href={provider.maps_url}
            target="_blank"
            rel="noreferrer"
          >
            Open in Google Maps
          </a>
        )}
        {provider.website && (
          <a
            className="text-xs font-semibold text-moss underline"
            href={provider.website}
            target="_blank"
            rel="noreferrer"
          >
            Website
          </a>
        )}
      </div>
    </article>
  );
}

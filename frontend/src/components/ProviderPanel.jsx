import { useMemo, useState } from "react";
import ProviderCard from "./ProviderCard.jsx";

const CATEGORIES = [
  ["", "Use conversation category"],
  ["plumbing", "Plumbing"],
  ["hvac", "HVAC"],
  ["electrical", "Electrical"],
  ["roofing", "Roofing"],
  ["water_damage", "Water damage"],
  ["pest_control", "Pest control"],
  ["appliance_repair", "Appliance repair"],
  ["handyman", "Handyman"],
];

export default function ProviderPanel({
  providers,
  selectedPlaceId,
  onSelect,
  onSearch,
  busy,
  searchSource,
  searchError,
}) {
  const [category, setCategory] = useState("");
  const [minRating, setMinRating] = useState(0);
  const [hasPhone, setHasPhone] = useState(false);
  const [sortBy, setSortBy] = useState("score");

  const visible = useMemo(() => {
    let rows = [...(providers || [])];
    if (minRating) {
      rows = rows.filter((p) => (p.rating || 0) >= Number(minRating));
    }
    if (hasPhone) {
      rows = rows.filter((p) => Boolean(p.phone));
    }
    rows.sort((a, b) => {
      if (sortBy === "rating") return (b.rating || 0) - (a.rating || 0);
      if (sortBy === "reviews") return (b.review_count || 0) - (a.review_count || 0);
      return (b.match_score || 0) - (a.match_score || 0);
    });
    return rows;
  }, [providers, minRating, hasPhone, sortBy]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <form
        className="grid grid-cols-1 gap-2 rounded-2xl bg-white/70 p-3 ring-1 ring-emerald-950/10 sm:grid-cols-2"
        onSubmit={(event) => {
          event.preventDefault();
          onSearch(category || null);
        }}
      >
        <label className="text-xs font-semibold text-ink/70 sm:col-span-2">
          Category
          <select
            className="mt-1 w-full rounded-xl border border-emerald-950/10 bg-white px-3 py-2 text-sm"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            {CATEGORIES.map(([value, label]) => (
              <option key={value || "auto"} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="submit"
          disabled={busy}
          className="rounded-xl bg-moss px-3 py-2 text-sm font-semibold text-white hover:bg-moss-dark disabled:opacity-50 sm:col-span-2"
        >
          {busy ? "Searching..." : "Search providers"}
        </button>
      </form>

      <div className="flex flex-wrap gap-2 text-xs">
        <label className="flex items-center gap-1 rounded-full bg-white px-3 py-1 ring-1 ring-emerald-950/10">
          Min rating
          <select
            className="bg-transparent"
            value={minRating}
            onChange={(event) => setMinRating(Number(event.target.value))}
          >
            <option value={0}>Any</option>
            <option value={3}>3+</option>
            <option value={4}>4+</option>
            <option value={4.5}>4.5+</option>
          </select>
        </label>
        <label className="flex items-center gap-1 rounded-full bg-white px-3 py-1 ring-1 ring-emerald-950/10">
          <input
            type="checkbox"
            checked={hasPhone}
            onChange={(event) => setHasPhone(event.target.checked)}
          />
          Has phone
        </label>
        <label className="flex items-center gap-1 rounded-full bg-white px-3 py-1 ring-1 ring-emerald-950/10">
          Sort
          <select
            className="bg-transparent"
            value={sortBy}
            onChange={(event) => setSortBy(event.target.value)}
          >
            <option value="score">Match score</option>
            <option value="rating">Rating</option>
            <option value="reviews">Reviews</option>
          </select>
        </label>
      </div>

      {searchError && (
        <p className="rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-950">{searchError}</p>
      )}

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto pr-1">
        {visible.length === 0 ? (
          <p className="rounded-2xl bg-white/70 p-4 text-sm text-ink/70">
            No providers to show yet. Set a city or ZIP at the top, describe the problem in
            chat, or search from this panel.
          </p>
        ) : (
          visible.map((provider) => (
            <ProviderCard
              key={provider.place_id}
              provider={provider}
              selected={provider.place_id === selectedPlaceId}
              onSelect={onSelect}
            />
          ))
        )}
      </div>

      <p className="text-[11px] text-ink/50">
        {searchSource === "google_places"
          ? "Provider listings from Google. Powered by Google."
          : "Fallback listings are recorded API data, not invented businesses. Powered by Google when live search is configured."}
      </p>
    </div>
  );
}

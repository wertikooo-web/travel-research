import type { Candidate, DestinationHotelResearch, FactResult, HotelPropertyResult, HotelSearchOutcome } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  success: "OK",
  partial: "частично",
  failed: "ошибка",
  unknown: "неизвестно",
  pending: "в процессе",
};

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "success"
      ? "bg-green-100 text-green-700"
      : status === "partial"
        ? "bg-amber-100 text-amber-700"
        : status === "failed"
          ? "bg-red-100 text-red-700"
          : "bg-gray-100 text-gray-600";
  return <span className={`rounded-full px-2 py-0.5 text-xs ${color}`}>{STATUS_LABEL[status] ?? status}</span>;
}

function factLabel<T>(fact: FactResult<T>, format: (v: T) => string): string {
  if (fact.status !== "known" || fact.value == null) return "неизвестно";
  return format(fact.value);
}

function boolFactLabel(fact: FactResult<boolean>): string {
  if (fact.status !== "known" || fact.value == null) return "неизвестно";
  return fact.value ? "да (подтверждено)" : "нет";
}

const INSPECTION_LABEL: Record<string, string> = {
  summary_only: "только сводка",
  rates_fetched: "тарифы проверены",
  rates_fetch_failed: "ошибка проверки тарифов",
};

function PropertyCard({ prop }: { prop: HotelPropertyResult }) {
  const p = prop.property;
  return (
    <div className="rounded border border-gray-100 p-3">
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-900">{p.name || "Без названия"}</span>
        <span className="text-xs text-gray-500">{INSPECTION_LABEL[prop.inspection_status] ?? prop.inspection_status}</span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-gray-600">
        <span>⭐ {factLabel(p.star_rating, (v) => String(v))}</span>
        <span>
          отзывы: {factLabel(p.review_score, (v) => v.toFixed(1))}
          {p.review_count.status === "known" ? ` (${p.review_count.value})` : ""}
        </span>
        <span>пляж: {boolFactLabel(p.beachfront)}</span>
      </div>
      {prop.cheapest_total_amount != null && (
        <div className="mt-1 text-sm font-semibold text-gray-900">
          от {prop.cheapest_total_amount} {prop.cheapest_total_currency}
          <span className="ml-1 text-xs font-normal text-gray-500">за всё проживание</span>
        </div>
      )}

      {prop.inspection_status === "rates_fetch_failed" && (
        <div className="mt-1 text-xs text-red-600">⚠ {prop.rates_fetch_error}</div>
      )}

      {prop.rooms.length > 0 && (
        <div className="mt-2 flex flex-col gap-2">
          {prop.rooms.map((room) => {
            const rates = prop.rates.filter((r) => r.room_id === room.provider_room_id);
            return (
              <div key={room.provider_room_id} className="rounded bg-gray-50 p-2 text-xs">
                <div className="font-medium text-gray-800">{room.name}</div>
                <div className="mt-0.5 flex flex-wrap gap-x-3 text-gray-600">
                  <span>вид на море: {boolFactLabel(room.sea_view)}</span>
                  <span>балкон: {boolFactLabel(room.balcony)}</span>
                  {room.bed_info && <span>{room.bed_info}</span>}
                </div>
                {rates.map((rate) => (
                  <div key={rate.provider_rate_id} className="mt-1 flex flex-wrap items-center gap-x-3 border-t border-gray-200 pt-1">
                    <span className="font-medium text-gray-900">
                      {rate.total_amount} {rate.total_currency}
                    </span>
                    {rate.nightly_equivalent.status === "known" && (
                      <span className="text-gray-500">≈{rate.nightly_equivalent.value}/ночь</span>
                    )}
                    <span>питание: {factLabel(rate.board_type, (v) => v)}</span>
                    <span>возврат: {boolFactLabel(rate.refundable)}</span>
                    <span>оплата: {factLabel(rate.payment_timing, (v) => (v === "pay_now" ? "сразу" : "на месте"))}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function SearchOutcomeCard({ outcome }: { outcome: HotelSearchOutcome }) {
  return (
    <div className="rounded border border-gray-100 p-2">
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>
          {outcome.plan.check_in} → {outcome.plan.check_out} ({outcome.plan.nights} ноч.,{" "}
          {outcome.plan.date_variant === "exact" ? "точные даты" : outcome.plan.date_variant}) · радиус{" "}
          {outcome.plan.radius_km} км
        </span>
        <StatusBadge status={outcome.status} />
      </div>
      {outcome.status === "failed" && <div className="mt-1 text-xs text-red-600">⚠ {outcome.error}</div>}
      {outcome.status === "success" && outcome.properties.length === 0 && (
        <div className="mt-1 text-xs text-gray-400">{outcome.note ?? "отелей не найдено"}</div>
      )}
      {outcome.status === "success" && outcome.properties.length > 0 && (
        <div className="mt-2 flex flex-col gap-2">
          {outcome.properties.map((p) => (
            <PropertyCard key={p.search_result_id} prop={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function DestinationCard({ hotel, candidate }: { hotel: DestinationHotelResearch; candidate: Candidate | undefined }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-gray-900">{candidate?.destination_name ?? hotel.candidate_id}</div>
        <div className="flex gap-1">
          <StatusBadge status={hotel.geography_status} />
          <StatusBadge status={hotel.date_status} />
          <StatusBadge status={hotel.overall_status} />
        </div>
      </div>

      {hotel.searches.length > 0 && (
        <div className="flex flex-col gap-2">
          {hotel.searches.map((s, i) => (
            <SearchOutcomeCard key={i} outcome={s} />
          ))}
        </div>
      )}

      {(hotel.warnings.length > 0 || hotel.errors.length > 0) && (
        <div className="mt-2 text-xs">
          {hotel.errors.map((e, i) => (
            <div key={`e${i}`} className="text-red-600">
              ⚠ {e}
            </div>
          ))}
          {hotel.warnings.map((w, i) => (
            <div key={`w${i}`} className="text-amber-600">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function HotelResearchView({
  results,
  candidates,
  runWarnings,
}: {
  results: DestinationHotelResearch[];
  candidates: Candidate[];
  runWarnings: string[];
}) {
  const candidateById = new Map(candidates.map((c) => [c.id, c]));

  return (
    <div className="flex flex-col gap-4">
      {runWarnings.length > 0 && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-800">
          {runWarnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}
      {results.map((r) => (
        <DestinationCard key={r.candidate_id} hotel={r} candidate={candidateById.get(r.candidate_id)} />
      ))}
    </div>
  );
}

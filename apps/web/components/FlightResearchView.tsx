import type { Candidate, DestinationFlightResearch, FlightOffer, FlightSearchOutcome } from "@/lib/types";

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

function formatDuration(minutes: number | null): string {
  if (minutes == null) return "?";
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return `${h}ч${m ? ` ${m}м` : ""}`;
}

function isExpired(expiresAt: string | null): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt).getTime() < Date.now();
}

function OfferRow({ offer, label }: { offer: FlightOffer; label: string }) {
  const expired = isExpired(offer.expires_at);
  const outCarrier = offer.outbound.segments[0]?.marketing_carrier ?? offer.outbound.segments[0]?.operating_carrier;
  return (
    <div className={`rounded border p-2 text-sm ${expired ? "border-red-200 bg-red-50" : "border-gray-100 bg-gray-50"}`}>
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-800">{label}</span>
        <span className="font-semibold text-gray-900">
          {offer.total_amount} {offer.total_currency}
          <span className="ml-1 text-xs font-normal text-gray-500">за {offer.traveller_count} чел.</span>
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-gray-600">
        <span>
          Туда: {offer.outbound.connections === 0 ? "прямой" : `${offer.outbound.connections} пересадка(и)`} ·{" "}
          {formatDuration(offer.outbound.duration_minutes)} · {outCarrier ?? "?"}
        </span>
        {offer.return_ && (
          <span>
            Обратно: {offer.return_.connections === 0 ? "прямой" : `${offer.return_.connections} пересадка(и)`} ·{" "}
            {formatDuration(offer.return_.duration_minutes)}
          </span>
        )}
      </div>
      <div className="mt-1 text-xs text-gray-400">
        проверено {new Date(offer.retrieved_at).toLocaleString("ru-RU")}
        {offer.expires_at && (
          <>
            {" "}
            · {expired ? <span className="font-medium text-red-600">предложение устарело</span> : `действует до ${new Date(offer.expires_at).toLocaleString("ru-RU")}`}
          </>
        )}
      </div>
    </div>
  );
}

function SearchOutcomeCard({ outcome }: { outcome: FlightSearchOutcome }) {
  const cheapest = outcome.offers.length
    ? [...outcome.offers].sort((a, b) => a.total_amount - b.total_amount)[0]
    : null;
  const shortest = outcome.offers.length
    ? [...outcome.offers].sort((a, b) => (a.outbound.duration_minutes ?? 1e9) - (b.outbound.duration_minutes ?? 1e9))[0]
    : null;

  return (
    <div className="rounded border border-gray-100 p-2">
      <div className="flex items-center justify-between text-xs text-gray-500">
        <span>
          {outcome.plan.outbound_date} → {outcome.plan.return_date} ({outcome.plan.nights} ноч.,{" "}
          {outcome.plan.date_variant === "exact" ? "точные даты" : outcome.plan.date_variant})
        </span>
        <StatusBadge status={outcome.status} />
      </div>
      {outcome.status === "failed" && <div className="mt-1 text-xs text-red-600">⚠ {outcome.error}</div>}
      {outcome.status === "success" && outcome.offers.length === 0 && (
        <div className="mt-1 text-xs text-gray-400">{outcome.note ?? "предложений не найдено"}</div>
      )}
      {outcome.status === "success" && outcome.offers.length > 0 && (
        <div className="mt-2 flex flex-col gap-1">
          <OfferRow offer={cheapest!} label="Дешевле всего" />
          {shortest && shortest.id !== cheapest!.id && <OfferRow offer={shortest} label="Быстрее всего" />}
          <div className="text-xs text-gray-400">всего предложений: {outcome.offers.length}</div>
        </div>
      )}
    </div>
  );
}

function DestinationCard({ flight, candidate }: { flight: DestinationFlightResearch; candidate: Candidate | undefined }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-gray-900">{candidate?.destination_name ?? flight.candidate_id}</div>
        <div className="flex gap-1">
          <StatusBadge status={flight.resolution_status} />
          <StatusBadge status={flight.date_status} />
          <StatusBadge status={flight.overall_status} />
        </div>
      </div>

      {flight.origin_place && flight.destination_place && (
        <div className="mb-2 text-xs text-gray-500">
          {flight.origin_place.iata_code} → {flight.destination_place.iata_code} ({flight.destination_place.name})
        </div>
      )}

      {flight.searches.length > 0 && (
        <div className="flex flex-col gap-2">
          {flight.searches.map((s, i) => (
            <SearchOutcomeCard key={i} outcome={s} />
          ))}
        </div>
      )}

      {(flight.warnings.length > 0 || flight.errors.length > 0) && (
        <div className="mt-2 text-xs">
          {flight.errors.map((e, i) => (
            <div key={`e${i}`} className="text-red-600">
              ⚠ {e}
            </div>
          ))}
          {flight.warnings.map((w, i) => (
            <div key={`w${i}`} className="text-amber-600">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function FlightResearchView({
  results,
  candidates,
  runWarnings,
}: {
  results: DestinationFlightResearch[];
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
        <DestinationCard key={r.candidate_id} flight={r} candidate={candidateById.get(r.candidate_id)} />
      ))}
    </div>
  );
}

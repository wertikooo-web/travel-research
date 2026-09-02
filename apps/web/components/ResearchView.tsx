import type { Candidate, DestinationResearch, FactResult, VisaResult } from "@/lib/types";

const STATUS_LABEL: Record<string, string> = {
  success: "OK",
  partial: "частично",
  failed: "ошибка",
  unknown: "неизвестно",
  pending: "в процессе",
};

const VISA_STATUS_LABEL: Record<string, string> = {
  visa_free: "без визы",
  visa_on_arrival: "виза по прибытии",
  evisa: "электронная виза",
  electronic_authorization: "электронное разрешение",
  visa_required: "нужна виза",
  entry_restricted: "въезд ограничен",
  unknown: "неизвестно",
};

function StatusBadge({ status }: { status: string }) {
  const color =
    status === "success" || status === "known"
      ? "bg-green-100 text-green-700"
      : status === "partial"
        ? "bg-amber-100 text-amber-700"
        : status === "failed" || status === "unavailable"
          ? "bg-red-100 text-red-700"
          : "bg-gray-100 text-gray-600";
  return <span className={`rounded-full px-2 py-0.5 text-xs ${color}`}>{STATUS_LABEL[status] ?? status}</span>;
}

function FactRow({ label, fact, unit }: { label: string; fact: FactResult<number>; unit?: string }) {
  return (
    <div className="flex items-baseline gap-2 text-sm">
      <span className="text-gray-500">{label}:</span>
      {fact.status === "known" ? (
        <span className="font-medium text-gray-900">
          {fact.value}
          {unit}
        </span>
      ) : (
        <span className="italic text-gray-400">{fact.status === "unavailable" ? "нет данных" : "неизвестно"}</span>
      )}
      {fact.note && <span className="text-xs text-gray-400">({fact.note})</span>}
    </div>
  );
}

function VisaRow({ visa }: { visa: VisaResult }) {
  const flag = visa.passport_country ? `🛂 ${visa.passport_country}` : "🛂 паспорт неизвестен";
  const evidence = visa.entry_methods.evidence[0];
  const methods = visa.entry_methods.status === "known" ? (visa.entry_methods.value ?? []) : [];
  return (
    <div className="rounded border border-gray-100 bg-gray-50 p-2 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium text-gray-800">{flag}</span>
        {methods.length === 0 && <span className="italic text-gray-400">неизвестно</span>}
      </div>
      {methods.length > 0 && (
        <div className="flex flex-col gap-0.5">
          {methods.map((m, i) => (
            <div key={i} className="flex items-baseline justify-between text-gray-900">
              <span>{VISA_STATUS_LABEL[m.method] ?? m.method}</span>
              {m.allowed_stay_days != null && <span className="text-xs text-gray-500">до {m.allowed_stay_days} дней</span>}
            </div>
          ))}
          {methods.length > 1 && <div className="text-xs text-gray-400">(источник указывает несколько вариантов)</div>}
        </div>
      )}
      {visa.entry_methods.note && <div className="text-xs text-gray-400">{visa.entry_methods.note}</div>}
      {evidence && (
        <div className="mt-1 text-xs text-gray-400">
          источник:{" "}
          {evidence.url ? (
            <a href={evidence.url} target="_blank" rel="noreferrer" className="underline">
              {evidence.provider}
            </a>
          ) : (
            evidence.provider
          )}{" "}
          · проверено {new Date(evidence.retrieved_at).toLocaleDateString("ru-RU")} · доверие: {evidence.confidence}
        </div>
      )}
    </div>
  );
}

function DestinationCard({ research, candidate }: { research: DestinationResearch; candidate: Candidate | undefined }) {
  return (
    <div className="rounded-lg border border-gray-200 p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="font-medium text-gray-900">
          {candidate?.destination_name ?? research.identity?.display_name ?? research.candidate_id}
          {research.identity?.country_code && <span className="ml-1 text-sm text-gray-500">({research.identity.country_code})</span>}
        </div>
        <div className="flex gap-1">
          <StatusBadge status={research.basics_status} />
          <StatusBadge status={research.weather_status} />
          <StatusBadge status={research.visa_status} />
        </div>
      </div>

      {research.weather && (
        <div className="mb-3 rounded border border-gray-100 bg-blue-50/50 p-2">
          <div className="mb-1 text-xs text-gray-500">
            {research.weather.period_basis === "historical_climate" ? "Типичная погода (историческая статистика)" : "Погода"}
            {research.weather.period_description && ` — ${research.weather.period_description}`}
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            <FactRow label="Днём" fact={research.weather.day_temp_c} unit="°C" />
            <FactRow label="Ночью" fact={research.weather.night_temp_c} unit="°C" />
            <FactRow label="Море" fact={research.weather.sea_temp_c} unit="°C" />
            <FactRow
              label="Дождливые дни"
              fact={{
                ...research.weather.rainy_day_ratio,
                value:
                  research.weather.rainy_day_ratio.value != null
                    ? Math.round(research.weather.rainy_day_ratio.value * 100)
                    : null,
              }}
              unit="%"
            />
          </div>
        </div>
      )}

      {research.visa_results.length > 0 && (
        <div className="mb-2">
          <div className="mb-1 text-xs text-gray-500">Виза / въезд</div>
          <div className="flex flex-col gap-1">
            {research.visa_results.map((v, i) => (
              <VisaRow key={i} visa={v} />
            ))}
          </div>
        </div>
      )}

      {(research.warnings.length > 0 || research.errors.length > 0) && (
        <div className="mt-2 text-xs">
          {research.errors.map((e, i) => (
            <div key={`e${i}`} className="text-red-600">
              ⚠ {e}
            </div>
          ))}
          {research.warnings.map((w, i) => (
            <div key={`w${i}`} className="text-amber-600">
              ⚠ {w}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default function ResearchView({
  results,
  candidates,
  runWarnings,
}: {
  results: DestinationResearch[];
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
        <DestinationCard key={r.candidate_id} research={r} candidate={candidateById.get(r.candidate_id)} />
      ))}
    </div>
  );
}

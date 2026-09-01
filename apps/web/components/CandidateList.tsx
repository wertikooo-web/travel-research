import type { Candidate, CandidateCategory } from "@/lib/types";

const CATEGORY_LABELS: Record<CandidateCategory, string> = {
  core: "Core",
  alternative: "Alternative",
  wildcard: "Wildcard",
};

const CATEGORY_ORDER: CandidateCategory[] = ["core", "alternative", "wildcard"];

function CandidateCard({ candidate }: { candidate: Candidate }) {
  return (
    <div className="rounded border border-gray-200 bg-white p-3">
      <div className="flex items-center justify-between">
        <div className="font-medium text-gray-900">
          {candidate.destination_name}
          {candidate.country_code && <span className="ml-1 text-sm text-gray-500">({candidate.country_code})</span>}
        </div>
        {candidate.source === "user" && (
          <span className="rounded-full bg-blue-100 px-2 py-0.5 text-xs text-blue-700">Ваш выбор</span>
        )}
      </div>
      <p className="mt-1 text-sm text-gray-700">{candidate.reason_to_check}</p>
      {candidate.potential_conflicts.length > 0 && (
        <ul className="mt-2 list-inside list-disc text-xs text-amber-700">
          {candidate.potential_conflicts.map((c, i) => (
            <li key={i}>{c}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function CandidateList({ candidates }: { candidates: Candidate[] }) {
  if (candidates.length === 0) {
    return (
      <p className="text-sm text-gray-500">
        Не удалось подобрать направления для этого брифа. Попробуйте изменить запрос и подтвердить заново.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {CATEGORY_ORDER.map((category) => {
        const items = candidates.filter((c) => c.candidate_category === category);
        if (items.length === 0) return null;
        return (
          <div key={category}>
            <h3 className="mb-2 font-medium text-gray-900">
              {CATEGORY_LABELS[category]} <span className="text-sm text-gray-400">({items.length})</span>
            </h3>
            <div className="flex flex-col gap-2">
              {items.map((c) => (
                <CandidateCard key={c.id} candidate={c} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

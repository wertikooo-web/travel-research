"use client";

import { useState } from "react";
import BriefConfirmation from "@/components/BriefConfirmation";
import TripInputForm from "@/components/TripInputForm";
import { ApiError, confirmBrief, createTrip, parseTrip, updateBrief } from "@/lib/api";
import type { BriefRecord, TripBrief, TripHints } from "@/lib/types";

type Stage = "input" | "confirm" | "confirmed";

export default function Home() {
  const [stage, setStage] = useState<Stage>("input");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [tripId, setTripId] = useState<string | null>(null);
  const [rawText, setRawText] = useState<string>("");
  const [brief, setBrief] = useState<BriefRecord | null>(null);

  async function handleSubmit(text: string, hints: TripHints | undefined) {
    setLoading(true);
    setError(null);
    setRawText(text);
    try {
      const trip = await createTrip();
      setTripId(trip.id);
      const parsed = await parseTrip(trip.id, text, hints);
      setBrief(parsed);
      setStage("confirm");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Что-то пошло не так. Попробуйте ещё раз.");
    } finally {
      setLoading(false);
    }
  }

  async function handleConfirm(edited: TripBrief) {
    if (!tripId) return;
    setLoading(true);
    setError(null);
    try {
      await updateBrief(tripId, edited);
      const confirmed = await confirmBrief(tripId);
      setBrief(confirmed);
      setStage("confirmed");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Не удалось сохранить бриф. Попробуйте ещё раз.");
    } finally {
      setLoading(false);
    }
  }

  function handleBack() {
    setStage("input");
    setError(null);
  }

  function handleStartOver() {
    setStage("input");
    setTripId(null);
    setBrief(null);
    setRawText("");
    setError(null);
  }

  return (
    <main className="mx-auto max-w-3xl px-4 py-12">
      <h1 className="mb-8 text-2xl font-bold text-gray-900">TripMatch</h1>

      {stage === "input" && (
        <TripInputForm onSubmit={handleSubmit} loading={loading} error={error} initialRawText={rawText} />
      )}

      {stage === "confirm" && brief && (
        <BriefConfirmation
          brief={brief.structured_brief}
          rawRequest={brief.raw_request}
          onConfirm={handleConfirm}
          onBack={handleBack}
          loading={loading}
          error={error}
        />
      )}

      {stage === "confirmed" && brief && (
        <div className="flex flex-col gap-4">
          <div className="rounded-lg border border-green-300 bg-green-50 p-4 text-green-800">
            Бриф подтверждён. Дальше — поиск направлений (следующий этап, ещё не реализован).
          </div>
          <pre className="overflow-x-auto rounded-lg bg-gray-900 p-4 text-xs text-gray-100">
            {JSON.stringify(brief.structured_brief, null, 2)}
          </pre>
          <button
            type="button"
            onClick={handleStartOver}
            className="self-start rounded-lg border border-gray-300 px-6 py-3 text-base font-medium text-gray-700 hover:bg-gray-50"
          >
            Начать заново
          </button>
        </div>
      )}
    </main>
  );
}

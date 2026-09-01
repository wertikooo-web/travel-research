"use client";

import { useState } from "react";
import type { TravellerHint, TripHints } from "@/lib/types";
import PassportPicker from "./PassportPicker";

interface TripInputFormProps {
  onSubmit: (rawText: string, hints: TripHints | undefined) => void;
  loading: boolean;
  error?: string | null;
  initialRawText?: string;
}

export default function TripInputForm({ onSubmit, loading, error, initialRawText }: TripInputFormProps) {
  const [rawText, setRawText] = useState(initialRawText ?? "");
  const [showDetails, setShowDetails] = useState(false);

  const [originText, setOriginText] = useState("");
  const [dateStart, setDateStart] = useState("");
  const [dateEnd, setDateEnd] = useState("");
  const [travellersCount, setTravellersCount] = useState<number | "">("");
  const [travellerHints, setTravellerHints] = useState<TravellerHint[]>([]);
  const [budgetMax, setBudgetMax] = useState<number | "">("");
  const [budgetCurrency, setBudgetCurrency] = useState("EUR");

  function handleTravellersCountChange(value: string) {
    const n = value === "" ? "" : Math.max(0, Math.min(12, parseInt(value, 10) || 0));
    setTravellersCount(n);
    if (n === "") return;
    setTravellerHints((prev) => {
      const next = [...prev];
      while (next.length < n) next.push({});
      next.length = n;
      return next;
    });
  }

  function updateTravellerHint(index: number, citizenships: string[] | null, travelPassport: string | null) {
    setTravellerHints((prev) => {
      const next = [...prev];
      next[index] = { citizenships, travel_passport: travelPassport };
      return next;
    });
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!rawText.trim() || loading) return;

    let hints: TripHints | undefined;
    if (showDetails) {
      hints = {
        origin_text: originText.trim() || null,
        date_start: dateStart || null,
        date_end: dateEnd || null,
        travellers_count: travellersCount === "" ? null : travellersCount,
        travellers: travellerHints.length ? travellerHints : null,
        budget_max_total: budgetMax === "" ? null : budgetMax,
        budget_currency: budgetMax === "" ? null : budgetCurrency,
      };
    }

    onSubmit(rawText.trim(), hints);
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-4">
      <div>
        <label className="mb-2 block text-lg font-medium text-gray-900">
          Куда вы хотите поехать? Расскажите о поездке своими словами.
        </label>
        <textarea
          value={rawText}
          onChange={(e) => setRawText(e.target.value)}
          rows={5}
          placeholder="Вдвоём из Кишинёва в конце октября на 7–10 дней. До €3500. Хочу море, тепло, красивый 4–5★ отель..."
          className="w-full rounded-lg border border-gray-300 p-4 text-base focus:border-blue-500 focus:outline-none"
          disabled={loading}
        />
      </div>

      <button
        type="button"
        onClick={() => setShowDetails((v) => !v)}
        className="self-start text-sm text-blue-600 hover:underline"
      >
        {showDetails ? "− Скрыть детали" : "+ Добавить детали (необязательно)"}
      </button>

      {showDetails && (
        <div className="flex flex-col gap-4 rounded-lg border border-gray-200 bg-gray-50 p-4">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Откуда вылет</label>
            <input
              value={originText}
              onChange={(e) => setOriginText(e.target.value)}
              placeholder="Кишинёв"
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-sm font-medium text-gray-700">Дата начала</label>
              <input
                type="date"
                value={dateStart}
                onChange={(e) => setDateStart(e.target.value)}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="flex-1">
              <label className="mb-1 block text-sm font-medium text-gray-700">Дата окончания</label>
              <input
                type="date"
                value={dateEnd}
                onChange={(e) => setDateEnd(e.target.value)}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">Количество путешественников</label>
            <input
              type="number"
              min={0}
              max={12}
              value={travellersCount}
              onChange={(e) => handleTravellersCountChange(e.target.value)}
              className="w-24 rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>

          {travellerHints.map((th, i) => (
            <div key={i} className="rounded border border-gray-200 bg-white p-3">
              <div className="mb-2 text-sm font-medium text-gray-700">
                Путешественник {i + 1}: с каким паспортом вы будете путешествовать?
              </div>
              <PassportPicker
                citizenships={th.citizenships}
                travelPassport={th.travel_passport}
                onChange={(c, p) => updateTravellerHint(i, c, p)}
              />
            </div>
          ))}

          <div className="flex gap-3">
            <div className="flex-1">
              <label className="mb-1 block text-sm font-medium text-gray-700">Бюджет, всего</label>
              <input
                type="number"
                min={0}
                value={budgetMax}
                onChange={(e) => setBudgetMax(e.target.value === "" ? "" : Number(e.target.value))}
                placeholder="3500"
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              />
            </div>
            <div className="w-28">
              <label className="mb-1 block text-sm font-medium text-gray-700">Валюта</label>
              <select
                value={budgetCurrency}
                onChange={(e) => setBudgetCurrency(e.target.value)}
                className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="EUR">EUR</option>
                <option value="USD">USD</option>
                <option value="MDL">MDL</option>
                <option value="RON">RON</option>
              </select>
            </div>
          </div>
        </div>
      )}

      {error && <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <button
        type="submit"
        disabled={!rawText.trim() || loading}
        className="self-start rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300"
      >
        {loading ? "Анализируем запрос…" : "Понять мою поездку"}
      </button>
    </form>
  );
}

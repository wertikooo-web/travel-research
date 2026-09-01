"use client";

import { useState } from "react";
import type { Traveller, TripBrief } from "@/lib/types";
import PassportPicker from "./PassportPicker";

interface BriefConfirmationProps {
  brief: TripBrief;
  rawRequest: string | null;
  onConfirm: (edited: TripBrief) => void;
  onBack: () => void;
  loading: boolean;
  error?: string | null;
}

function normalize(b: TripBrief): TripBrief {
  return {
    origin: b.origin ?? {},
    travellers: b.travellers ?? [],
    dates: b.dates ?? {},
    nights: b.nights ?? {},
    budget: b.budget ?? {},
    flight: b.flight ?? {},
    hotel: b.hotel ?? {},
    weather: b.weather ?? {},
    visa: b.visa ?? {},
    preferences: b.preferences ?? { avoid: [], prefer: [] },
  };
}

function TriState({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean | null | undefined;
  onChange: (v: boolean | null) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
      <select
        value={value === true ? "true" : value === false ? "false" : ""}
        onChange={(e) => onChange(e.target.value === "" ? null : e.target.value === "true")}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
      >
        <option value="">не указано</option>
        <option value="true">да</option>
        <option value="false">нет</option>
      </select>
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  width = "w-full",
}: {
  label: string;
  value: number | null | undefined;
  onChange: (v: number | null) => void;
  width?: string;
}) {
  return (
    <div className={width}>
      <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
      <input
        type="number"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
      />
    </div>
  );
}

function TagField({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (v: string[]) => void;
}) {
  const [text, setText] = useState(values.join(", "));
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">{label}</label>
      <input
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          onChange(
            e.target.value
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean)
          );
        }}
        placeholder="через запятую"
        className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
      />
    </div>
  );
}

export default function BriefConfirmation({ brief, rawRequest, onConfirm, onBack, loading, error }: BriefConfirmationProps) {
  const [edited, setEdited] = useState<TripBrief>(() => normalize(brief));

  function patchSection<K extends "origin" | "dates" | "nights" | "budget" | "flight" | "hotel" | "weather" | "visa">(
    key: K,
    value: Partial<NonNullable<TripBrief[K]>>
  ) {
    setEdited((prev) => ({ ...prev, [key]: { ...(prev[key] as object), ...value } }));
  }

  function updateTraveller(index: number, patch: Partial<Traveller>) {
    setEdited((prev) => {
      const travellers = [...prev.travellers];
      travellers[index] = { ...travellers[index], ...patch };
      return { ...prev, travellers };
    });
  }

  function addTraveller() {
    setEdited((prev) => ({
      ...prev,
      travellers: [...prev.travellers, { type: "adult" as const, id: `traveller_${prev.travellers.length + 1}` }],
    }));
  }

  function removeTraveller(index: number) {
    setEdited((prev) => ({ ...prev, travellers: prev.travellers.filter((_, i) => i !== index) }));
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Правильно ли я понял вашу поездку?</h2>
        {rawRequest && <p className="mt-1 text-sm text-gray-500">Ваш запрос: «{rawRequest}»</p>}
      </div>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Откуда</h3>
        <div className="flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium text-gray-700">Город</label>
            <input
              value={edited.origin?.text ?? ""}
              onChange={(e) => patchSection("origin", { text: e.target.value || null })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="w-28">
            <label className="mb-1 block text-sm font-medium text-gray-700">IATA</label>
            <input
              value={edited.origin?.iata ?? ""}
              onChange={(e) => patchSection("origin", { iata: e.target.value.toUpperCase() || null })}
              maxLength={3}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm uppercase"
            />
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Даты и ночи</h3>
        <div className="mb-3 flex gap-3">
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium text-gray-700">Начало</label>
            <input
              type="date"
              value={edited.dates?.start ?? ""}
              onChange={(e) => patchSection("dates", { start: e.target.value || null })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <div className="flex-1">
            <label className="mb-1 block text-sm font-medium text-gray-700">Конец</label>
            <input
              type="date"
              value={edited.dates?.end ?? ""}
              onChange={(e) => patchSection("dates", { end: e.target.value || null })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            />
          </div>
          <NumberField
            label="Гибкость, дней"
            value={edited.dates?.flex_days}
            onChange={(v) => patchSection("dates", { flex_days: v })}
            width="w-32"
          />
        </div>
        <div className="flex gap-3">
          <NumberField label="Ночей, мин" value={edited.nights?.min} onChange={(v) => patchSection("nights", { min: v })} />
          <NumberField label="Ночей, макс" value={edited.nights?.max} onChange={(v) => patchSection("nights", { max: v })} />
          <NumberField
            label="Ночей, предпочтительно"
            value={edited.nights?.preferred}
            onChange={(v) => patchSection("nights", { preferred: v })}
          />
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-medium text-gray-900">Путешественники</h3>
          <button type="button" onClick={addTraveller} className="text-sm text-blue-600 hover:underline">
            + добавить
          </button>
        </div>
        <div className="flex flex-col gap-4">
          {edited.travellers.map((t, i) => (
            <div key={t.id ?? i} className="rounded border border-gray-200 bg-gray-50 p-3">
              <div className="mb-2 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <select
                    value={t.type}
                    onChange={(e) => updateTraveller(i, { type: e.target.value as Traveller["type"] })}
                    className="rounded border border-gray-300 px-2 py-1 text-sm"
                  >
                    <option value="adult">взрослый</option>
                    <option value="child">ребёнок</option>
                  </select>
                  {t.type === "child" && (
                    <input
                      type="number"
                      min={0}
                      max={17}
                      value={t.age ?? ""}
                      onChange={(e) => updateTraveller(i, { age: e.target.value === "" ? null : Number(e.target.value) })}
                      placeholder="возраст"
                      className="w-20 rounded border border-gray-300 px-2 py-1 text-sm"
                    />
                  )}
                </div>
                <button type="button" onClick={() => removeTraveller(i)} className="text-sm text-red-500 hover:underline">
                  удалить
                </button>
              </div>

              <div className="mb-2 text-sm font-medium text-gray-700">Паспорт</div>
              <PassportPicker
                citizenships={t.citizenships}
                travelPassport={t.travel_passport}
                onChange={(citizenships, travel_passport) => updateTraveller(i, { citizenships, travel_passport })}
              />

              <div className="mt-2 w-48">
                <label className="mb-1 block text-sm font-medium text-gray-700">Тип паспорта</label>
                <select
                  value={t.passport_type ?? ""}
                  onChange={(e) =>
                    updateTraveller(i, { passport_type: (e.target.value || null) as Traveller["passport_type"] })
                  }
                  className="w-full rounded border border-gray-300 px-2 py-1 text-sm"
                >
                  <option value="">не указано</option>
                  <option value="biometric">биометрический</option>
                  <option value="ordinary">обычный</option>
                  <option value="other">другой</option>
                </select>
              </div>
            </div>
          ))}
          {edited.travellers.length === 0 && <p className="text-sm text-gray-400">Путешественники не добавлены</p>}
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Бюджет</h3>
        <div className="flex items-end gap-3">
          <NumberField
            label="Всего, макс."
            value={edited.budget?.max_total}
            onChange={(v) => patchSection("budget", { max_total: v })}
          />
          <div className="w-28">
            <label className="mb-1 block text-sm font-medium text-gray-700">Валюта</label>
            <select
              value={edited.budget?.currency ?? ""}
              onChange={(e) => patchSection("budget", { currency: e.target.value || null })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">—</option>
              <option value="EUR">EUR</option>
              <option value="USD">USD</option>
              <option value="MDL">MDL</option>
              <option value="RON">RON</option>
            </select>
          </div>
          <div className="w-40">
            <TriState
              label="Жёсткий лимит"
              value={edited.budget?.hard_constraint}
              onChange={(v) => patchSection("budget", { hard_constraint: v })}
            />
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Перелёт</h3>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-40">
            <TriState
              label="Предпочтителен прямой"
              value={edited.flight?.direct_preferred}
              onChange={(v) => patchSection("flight", { direct_preferred: v })}
            />
          </div>
          <NumberField
            label="Макс. пересадок"
            value={edited.flight?.max_connections}
            onChange={(v) => patchSection("flight", { max_connections: v })}
            width="w-40"
          />
          <NumberField
            label="Макс. длительность, ч"
            value={edited.flight?.max_duration_hours}
            onChange={(v) => patchSection("flight", { max_duration_hours: v })}
            width="w-48"
          />
          <div className="w-44">
            <label className="mb-1 block text-sm font-medium text-gray-700">Класс</label>
            <select
              value={edited.flight?.preferred_cabin ?? ""}
              onChange={(e) => patchSection("flight", { preferred_cabin: (e.target.value || null) as never })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">не указано</option>
              <option value="economy">эконом</option>
              <option value="premium_economy">премиум-эконом</option>
              <option value="business">бизнес</option>
              <option value="first">первый</option>
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Отель</h3>
        <div className="flex flex-wrap items-end gap-3">
          <NumberField
            label="Мин. звёзд"
            value={edited.hotel?.stars_min}
            onChange={(v) => patchSection("hotel", { stars_min: v })}
            width="w-32"
          />
          <div className="w-40">
            <TriState
              label="У моря / пляж"
              value={edited.hotel?.beachfront}
              onChange={(v) => patchSection("hotel", { beachfront: v })}
            />
          </div>
          <div className="w-40">
            <TriState
              label="Вид на море"
              value={edited.hotel?.sea_view}
              onChange={(v) => patchSection("hotel", { sea_view: v })}
            />
          </div>
          <div className="w-48">
            <label className="mb-1 block text-sm font-medium text-gray-700">Питание, мин.</label>
            <select
              value={edited.hotel?.meal_min ?? ""}
              onChange={(e) => patchSection("hotel", { meal_min: (e.target.value || null) as never })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">не указано</option>
              <option value="room_only">без питания</option>
              <option value="breakfast">завтрак</option>
              <option value="half_board">полупансион</option>
              <option value="full_board">полный пансион</option>
              <option value="all_inclusive">всё включено</option>
            </select>
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Погода и виза</h3>
        <div className="flex flex-wrap items-end gap-3">
          <NumberField
            label="Мин. темп. воздуха, °C"
            value={edited.weather?.day_temp_min}
            onChange={(v) => patchSection("weather", { day_temp_min: v })}
            width="w-48"
          />
          <NumberField
            label="Мин. темп. моря, °C"
            value={edited.weather?.sea_temp_min}
            onChange={(v) => patchSection("weather", { sea_temp_min: v })}
            width="w-48"
          />
          <div className="w-44">
            <label className="mb-1 block text-sm font-medium text-gray-700">Терпимость к дождю</label>
            <select
              value={edited.weather?.rain_tolerance ?? ""}
              onChange={(e) => patchSection("weather", { rain_tolerance: (e.target.value || null) as never })}
              className="w-full rounded border border-gray-300 px-3 py-2 text-sm"
            >
              <option value="">не указано</option>
              <option value="low">низкая</option>
              <option value="medium">средняя</option>
              <option value="high">высокая</option>
            </select>
          </div>
          <div className="w-44">
            <TriState
              label="Нужна простая виза"
              value={edited.visa?.easy_required}
              onChange={(v) => patchSection("visa", { easy_required: v })}
            />
          </div>
        </div>
      </section>

      <section className="rounded-lg border border-gray-200 p-4">
        <h3 className="mb-3 font-medium text-gray-900">Предпочтения</h3>
        <div className="flex flex-col gap-3">
          <TagField
            label="Избегать"
            values={edited.preferences?.avoid ?? []}
            onChange={(v) => setEdited((prev) => ({ ...prev, preferences: { avoid: v, prefer: prev.preferences?.prefer ?? [] } }))}
          />
          <TagField
            label="Хочется"
            values={edited.preferences?.prefer ?? []}
            onChange={(v) => setEdited((prev) => ({ ...prev, preferences: { avoid: prev.preferences?.avoid ?? [], prefer: v } }))}
          />
        </div>
      </section>

      {error && <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={onBack}
          disabled={loading}
          className="rounded-lg border border-gray-300 px-6 py-3 text-base font-medium text-gray-700 hover:bg-gray-50"
        >
          Изменить запрос
        </button>
        <button
          type="button"
          onClick={() => onConfirm(edited)}
          disabled={loading}
          className="rounded-lg bg-blue-600 px-6 py-3 text-base font-medium text-white hover:bg-blue-700 disabled:bg-gray-300"
        >
          {loading ? "Сохраняем…" : "Confirm trip brief"}
        </button>
      </div>
    </div>
  );
}

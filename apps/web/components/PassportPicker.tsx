"use client";

import { useState } from "react";

interface PassportPickerProps {
  citizenships: string[] | null | undefined;
  travelPassport: string | null | undefined;
  onChange: (citizenships: string[] | null, travelPassport: string | null) => void;
}

const QUICK_OPTIONS = [
  { code: "MD", flag: "🇲🇩", label: "Moldova" },
  { code: "RO", flag: "🇷🇴", label: "Romania" },
];

export default function PassportPicker({ citizenships, travelPassport, onChange }: PassportPickerProps) {
  const codes = citizenships ?? [];
  const [multiMode, setMultiMode] = useState(codes.length > 1);
  const [otherInput, setOtherInput] = useState("");
  const [showOtherInput, setShowOtherInput] = useState(false);

  function pickSingle(code: string) {
    setMultiMode(false);
    onChange([code], code);
  }

  function toggleMulti(code: string) {
    const has = codes.includes(code);
    const next = has ? codes.filter((c) => c !== code) : [...codes, code];
    const nextPassport = travelPassport && next.includes(travelPassport) ? travelPassport : null;
    onChange(next.length ? next : null, nextPassport);
  }

  function addOther() {
    const code = otherInput.trim().toUpperCase();
    if (code.length !== 2) return;
    if (multiMode) {
      if (!codes.includes(code)) onChange([...codes, code], travelPassport ?? null);
    } else {
      onChange([code], code);
    }
    setOtherInput("");
    setShowOtherInput(false);
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-2">
        {QUICK_OPTIONS.map((opt) => {
          const active = multiMode ? codes.includes(opt.code) : travelPassport === opt.code;
          return (
            <button
              key={opt.code}
              type="button"
              onClick={() => (multiMode ? toggleMulti(opt.code) : pickSingle(opt.code))}
              className={`rounded-full border px-3 py-1.5 text-sm transition ${
                active
                  ? "border-blue-600 bg-blue-50 text-blue-700"
                  : "border-gray-300 text-gray-700 hover:border-gray-400"
              }`}
            >
              {opt.flag} {opt.label}
            </button>
          );
        })}

        <button
          type="button"
          onClick={() => setShowOtherInput((v) => !v)}
          className={`rounded-full border px-3 py-1.5 text-sm transition ${
            showOtherInput ? "border-blue-600 bg-blue-50 text-blue-700" : "border-gray-300 text-gray-700 hover:border-gray-400"
          }`}
        >
          🌍 Other
        </button>

        <button
          type="button"
          onClick={() => {
            const next = !multiMode;
            setMultiMode(next);
            if (!next && codes.length > 1) onChange([codes[0]], codes[0]);
          }}
          className={`rounded-full border px-3 py-1.5 text-sm transition ${
            multiMode ? "border-blue-600 bg-blue-50 text-blue-700" : "border-gray-300 text-gray-700 hover:border-gray-400"
          }`}
        >
          Несколько паспортов
        </button>
      </div>

      {showOtherInput && (
        <div className="flex items-center gap-2">
          <input
            value={otherInput}
            onChange={(e) => setOtherInput(e.target.value)}
            placeholder="ISO-код страны, напр. US"
            maxLength={2}
            className="w-32 rounded border border-gray-300 px-2 py-1 text-sm uppercase"
          />
          <button
            type="button"
            onClick={addOther}
            className="rounded bg-gray-800 px-2 py-1 text-sm text-white hover:bg-gray-700"
          >
            Добавить
          </button>
        </div>
      )}

      {multiMode && codes.length > 1 && (
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <span>Едет по паспорту:</span>
          <select
            value={travelPassport ?? ""}
            onChange={(e) => onChange(codes, e.target.value || null)}
            className="rounded border border-gray-300 px-2 py-1"
          >
            <option value="">не указано</option>
            {codes.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </div>
      )}

      {!multiMode && codes.length === 0 && !showOtherInput && (
        <span className="text-xs text-gray-400">Паспорт не указан — оставим null, ничего не придумываем</span>
      )}
    </div>
  );
}

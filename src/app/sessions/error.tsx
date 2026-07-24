"use client";

export default function SessionsError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="panel grid min-h-[520px] place-items-center p-6 text-center">
      <div>
        <h2 className="text-xl font-semibold text-white">Sessions route failed</h2>
        <p className="mt-2 text-[11px] text-slate-500">Сторінка не підміняє помилку demo-даними.</p>
        <button className="primary-button mt-4" onClick={reset}>
          Повторити
        </button>
      </div>
    </div>
  );
}

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "NEXOLAB · Ранковий звіт",
  description: "Read-only Telegram Mini App for persisted NEXOLAB morning reports.",
  robots: { index: false, follow: false },
};

export default function TelegramMiniAppLayout({ children }: { children: React.ReactNode }) {
  return children;
}

import type { Metadata } from "next";
import { EngineStatusProvider, OfflineBanner, ProvidersBadge } from "@/components/engine-status";
import { QueueIndicator, QueueProvider } from "@/components/queue";
import { Sidebar } from "@/components/sidebar";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "mangaka-team", template: "%s · mangaka-team" },
  description: "Studio local de planches manga/BD assisté par IA",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="fr" className="h-full antialiased">
      <body className="min-h-full">
        <EngineStatusProvider>
          <QueueProvider>
            <div className="flex min-h-screen flex-col md:flex-row">
              <Sidebar />
              <div className="flex min-w-0 flex-1 flex-col">
                <header className="sticky top-0 z-30 flex flex-wrap items-center justify-end gap-3 border-b border-zinc-800 bg-zinc-950/90 px-6 py-2 backdrop-blur md:px-10">
                  <ProvidersBadge />
                  <QueueIndicator />
                </header>
                <OfflineBanner />
                <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 md:px-10">{children}</main>
              </div>
            </div>
          </QueueProvider>
        </EngineStatusProvider>
      </body>
    </html>
  );
}

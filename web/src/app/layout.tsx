import type { Metadata } from "next";
import { EngineStatusProvider, OfflineBanner } from "@/components/engine-status";
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
          <div className="flex min-h-screen flex-col md:flex-row">
            <Sidebar />
            <div className="flex min-w-0 flex-1 flex-col">
              <OfflineBanner />
              <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8 md:px-10">{children}</main>
            </div>
          </div>
        </EngineStatusProvider>
      </body>
    </html>
  );
}

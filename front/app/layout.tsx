import type { Metadata } from "next";
import "./globals.css";
import { RuntimeProvider } from "@/components/workspace/runtime";
import { readRuntimeSettings } from "@/lib/resolveqa/environment";

export const metadata: Metadata = {
  title: "Mola — ResolveQA",
  description:
    "Agentes para reproduzir, corrigir e verificar bugs com evidências, documentação atualizada e os procedimentos da sua empresa.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR">
      <body className="antialiased">
        <RuntimeProvider
          settings={readRuntimeSettings({
            RESOLVEQA_MODE: process.env.RESOLVEQA_MODE,
            RESOLVEQA_API_URL: process.env.RESOLVEQA_API_URL,
            RESOLVEQA_CASE_IDS: process.env.RESOLVEQA_CASE_IDS,
            RESOLVEQA_SNAPSHOT_PATH: process.env.RESOLVEQA_SNAPSHOT_PATH,
            RESOLVEQA_EVENTS_PATH: process.env.RESOLVEQA_EVENTS_PATH,
            RESOLVEQA_PLAYBOOKS_PATH: process.env.RESOLVEQA_PLAYBOOKS_PATH,
          })}
        >
          {children}
        </RuntimeProvider>
      </body>
    </html>
  );
}

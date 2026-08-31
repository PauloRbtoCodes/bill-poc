import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Contas a pagar",
  description: "POC de captura e extração de cobranças por e-mail",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <header className="border-b border-stone-200 bg-white">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
            <Link href="/" className="text-sm font-semibold tracking-tight">
              Contas a pagar
            </Link>
            <nav className="flex gap-1 text-sm">
              <Link
                href="/"
                className="rounded-md px-3 py-1.5 text-stone-600 transition hover:bg-stone-100 hover:text-stone-900"
              >
                Caixa de entrada
              </Link>
              <Link
                href="/agenda"
                className="rounded-md px-3 py-1.5 text-stone-600 transition hover:bg-stone-100 hover:text-stone-900"
              >
                Agenda de pagamento
              </Link>
            </nav>
            <span className="ml-auto text-xs text-stone-400">Cliente Demo Ltda</span>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}

import type { Metadata } from "next";
import { Inter, Outfit } from "next/font/google";
import Link from "next/link";
import "./globals.css";

// Outfit para títulos (geométrica, tech-forward) e Inter para o funcional.
// Carregadas pelo next/font: sem requisição extra em runtime e sem flash de
// fonte trocando no meio da leitura.
const outfit = Outfit({
  subsets: ["latin"],
  variable: "--font-outfit",
  weight: ["600", "700"],
});

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  weight: ["400", "500", "600"],
});

export const metadata: Metadata = {
  title: "Contas a pagar",
  description: "Captura e extração de cobranças por e-mail, com auditoria por campo",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" className={`${outfit.variable} ${inter.variable}`}>
      <body>
        <header className="sticky top-0 z-30">
          <div className="glass border-x-0 border-t-0">
            <div className="mx-auto flex max-w-[1280px] items-center gap-6 px-6 py-3 md:px-12">
              <Link href="/" className="flex items-center gap-2.5">
                {/* O ponto com brilho é o único elemento puramente decorativo da
                    interface: marca o "sistema ativo" sem custar espaço. */}
                <span
                  className="size-2 rounded-full"
                  style={{
                    background: "linear-gradient(135deg,var(--color-electric-indigo),var(--color-soft-lilac))",
                    boxShadow: "0 0 10px 1px rgba(75,57,239,.7)",
                  }}
                />
                <span className="headline-md text-[17px] leading-none tracking-tight text-mist-white">
                  Contas a pagar
                </span>
              </Link>

              <nav className="flex gap-1 text-sm">
                <Link
                  href="/"
                  className="rounded-full px-3 py-1.5 text-on-surface-variant transition hover:bg-white/8 hover:text-mist-white"
                >
                  Caixa de entrada
                </Link>
                <Link
                  href="/agenda"
                  className="rounded-full px-3 py-1.5 text-on-surface-variant transition hover:bg-white/8 hover:text-mist-white"
                >
                  Agenda
                </Link>
              </nav>

              <span className="label-sm ml-auto hidden text-outline sm:block">
                Cliente Demo Ltda
              </span>
            </div>
          </div>
        </header>

        <main className="mx-auto max-w-[1280px] px-6 py-10 md:px-12">{children}</main>
      </body>
    </html>
  );
}

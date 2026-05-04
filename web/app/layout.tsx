import type { Metadata } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import Link from "next/link";
import { Terminal } from "lucide-react";

const jakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-jakarta",
});

export const metadata: Metadata = {
  title: "repi | Log Investigation",
  description: "Autonomous log investigation with ReAct loop",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${jakarta.variable} font-sans antialiased min-h-screen bg-background text-foreground`}
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          <div className="relative flex min-h-screen flex-col">
            <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <div className="container flex h-14 items-center max-w-7xl mx-auto px-4">
                <div className="mr-4 flex">
                  <Link href="/investigations" className="mr-6 flex items-center space-x-2">
                    <Terminal className="h-6 w-6 text-primary" />
                    <span className="font-bold inline-block">repi</span>
                  </Link>
                  <nav className="flex items-center space-x-6 text-sm font-medium">
                    <Link
                      href="/investigations"
                      className="transition-colors hover:text-foreground/80 text-foreground"
                    >
                      Investigations
                    </Link>
                    <Link
                      href="/config"
                      className="transition-colors hover:text-foreground/80 text-foreground/60"
                    >
                      Config
                    </Link>
                  </nav>
                </div>
              </div>
            </header>
            <main className="flex-1 flex flex-col">{children}</main>
          </div>
          <Toaster position="top-right" />
        </ThemeProvider>
      </body>
    </html>
  );
}

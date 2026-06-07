import type { Metadata } from 'next';
import './globals.css';
import { Shell } from '@/components/layout/Shell';

export const metadata: Metadata = {
  title: 'ScoutIQ — NBA Contract Intelligence',
  description: 'Explainable NBA contract valuation and cap simulation for front-office decision-making.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <body className="h-full" suppressHydrationWarning>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

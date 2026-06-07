import type { Metadata } from 'next';
import './globals.css';
import { Shell } from '@/components/layout/Shell';

export const metadata: Metadata = {
  title: 'ScoutIQ — NBA Contract Intelligence',
  description: 'Explainable NBA contract valuation and cap simulation for front-office decision-making.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}

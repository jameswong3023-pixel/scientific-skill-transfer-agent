import Link from "next/link";
import { ArrowRight, Beaker, Brain, FileText } from "lucide-react";

const CARDS = [
  { href: "/papers", icon: FileText, title: "1. Upload a paper",
    body: "The agent reads the methods and extracts an implementable skill, with every claim traced to a quote and page." },
  { href: "/datasets", icon: Beaker, title: "2. Provide imaging data",
    body: "NIfTI, DICOM, TIFF stacks or plain images. Ground-truth labels stay withheld from both agents." },
  { href: "/experiments/new", icon: Brain, title: "3. Run the A/B experiment",
    body: "The same agent solves the same task twice — once with the paper's technique, once without." },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl space-y-10 p-6 py-14">
      <div className="space-y-4">
        <h1 className="text-4xl font-semibold tracking-tight text-slate-100">
          Can an agent learn a technique from a paper?
        </h1>
        <p className="max-w-2xl text-lg text-slate-400">
          Upload a scientific methods paper. The agent extracts the procedure as a reusable
          skill, then solves an unseen imaging task twice — with the skill and without it — so
          you can see, quantitatively, whether the paper helped.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        {CARDS.map(({ href, icon: Icon, title, body }) => (
          <Link key={href} href={href} className="panel group p-5 transition hover:border-violet-500/40">
            <Icon size={20} className="text-violet-400" />
            <h2 className="mt-3 font-medium text-slate-100">{title}</h2>
            <p className="mt-1.5 text-sm text-slate-400">{body}</p>
            <span className="mt-3 inline-flex items-center gap-1 text-sm text-violet-400 opacity-0 transition group-hover:opacity-100">
              Go <ArrowRight size={14} />
            </span>
          </Link>
        ))}
      </div>
    </main>
  );
}

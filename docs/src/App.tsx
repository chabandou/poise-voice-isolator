import Hero from './components/Hero';
import Navbar from './components/Navbar';
import Steps from './components/Steps';
import AppPreview from './components/AppPreview';
import Grid from './components/Grid';
import Quote from './components/Quote';
import Transparency from './components/Transparency';
import FinalCTA from './components/FinalCTA';
import Footer from './components/Footer';
import { useReveal } from './reveal';

export default function App() {
  useReveal();

  return (
    <div className="min-h-screen overflow-x-hidden bg-bg text-ink">
      <Navbar />
      <main>
        <Hero />
        <Steps />
        <AppPreview />
        <Grid />
        <Quote />
        <Transparency />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}

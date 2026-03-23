import Hero from './components/Hero';
import Navbar from './components/Navbar';
import Steps from './components/Steps';
import Grid from './components/Grid';
import Quote from './components/Quote';
import Transparency from './components/Transparency';
import FinalCTA from './components/FinalCTA';
import Footer from './components/Footer';

export default function App() {
  return (
    <div className="min-h-screen bg-background text-white overflow-x-hidden">
      <Navbar />
      <main>
        <Hero />
        <Steps />
        <Grid />
        <Quote />
        <Transparency />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
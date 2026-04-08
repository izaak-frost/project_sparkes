import { useEffect, useState } from 'react';
import { StyleSheet } from 'react-native';

import { Collapsible } from '@/components/ui/collapsible';
import ParallaxScrollView from '@/components/parallax-scroll-view';
import { ThemedText } from '@/components/themed-text';
import { ThemedView } from '@/components/themed-view';
import { IconSymbol } from '@/components/ui/icon-symbol';
import { Fonts } from '@/constants/theme';

type Weight = {
  date: string;
  weight: number;
};

type Step = {
  date: string;
  steps: number;
};

export default function TabTwoScreen() {
  const API_BASE_URL = 'http://192.168.0.28:8000';

  const [status, setStatus] = useState('Loading...');
  const [weights, setWeights] = useState<Weight[]>([]);
  const [steps, setSteps] = useState<Step[]>([]);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setStatus('Fetching data...');

        const weightsResponse = await fetch(`${API_BASE_URL}/weights`);
        const stepsResponse = await fetch(`${API_BASE_URL}/steps`);

        const weightsData = await weightsResponse.json();
        const stepsData = await stepsResponse.json();

        setWeights(Array.isArray(weightsData) ? weightsData : []);
        setSteps(Array.isArray(stepsData) ? stepsData : []);

        setStatus('Loaded successfully');
      } catch (error) {
        const message =
          error instanceof Error ? error.message : 'Unknown error';

        setStatus(`Error: ${message}`);
        console.error(error);
      }
    };

    fetchData();
  }, []);

  return (
    <ParallaxScrollView
      headerBackgroundColor={{ light: '#D0D0D0', dark: '#353636' }}
      headerImage={
        <IconSymbol
          size={310}
          color="#808080"
          name="chevron.left.forwardslash.chevron.right"
          style={styles.headerImage}
        />
      }>
      <ThemedView style={styles.titleContainer}>
        <ThemedText type="title" style={{ fontFamily: Fonts.rounded }}>
          Explore
        </ThemedText>
      </ThemedView>

      <ThemedText>Status: {status}</ThemedText>

      {/* Weights */}
      <Collapsible title="Weights">
        {weights.length === 0 ? (
          <ThemedText>No weight data</ThemedText>
        ) : (
          weights.map((item, index) => (
            <ThemedView key={`weight-${index}`} style={styles.row}>
              <ThemedText style={styles.date}>{item.date}</ThemedText>
              <ThemedText style={styles.value}>{item.weight} kg</ThemedText>
            </ThemedView>
          ))
        )}
      </Collapsible>

      {/* Steps */}
      <Collapsible title="Steps">
        {steps.length === 0 ? (
          <ThemedText>No step data</ThemedText>
        ) : (
          steps.map((item, index) => (
            <ThemedView key={`step-${index}`} style={styles.row}>
              <ThemedText style={styles.date}>{item.date}</ThemedText>
              <ThemedText style={styles.value}>{item.steps} steps</ThemedText>
            </ThemedView>
          ))
        )}
      </Collapsible>
    </ParallaxScrollView>
  );
}

const styles = StyleSheet.create({
  headerImage: {
    color: '#808080',
    bottom: -90,
    left: -35,
    position: 'absolute',
  },
  titleContainer: {
    flexDirection: 'row',
    gap: 8,
  },
  row: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    paddingVertical: 6,
    borderBottomWidth: 0.5,
    borderColor: '#ccc',
  },
  date: {
    fontFamily: Fonts.mono,
    fontSize: 12,
  },
  value: {
    fontWeight: 'bold',
  },
});
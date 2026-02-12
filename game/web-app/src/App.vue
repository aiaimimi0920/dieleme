<script setup>
import { useGameState } from './composables/useGameState.js'
import HomeView from './views/HomeView.vue'
import CandleGame from './views/CandleGame.vue'
import ScaleGame from './views/ScaleGame.vue'
import WheelGame from './views/WheelGame.vue'
import PosterView from './views/PosterView.vue'

const { currentView } = useGameState()
</script>

<template>
  <div>
    <header class="p-4 border-b border-gray-800 flex justify-between items-center">
      <h1 class="text-xl font-bold bg-gradient-to-r from-red-500 to-purple-600 bg-clip-text text-transparent">
        你的房还值多少？
      </h1>
    </header>
    <HomeView v-if="currentView === 'home'" />
    <CandleGame v-else-if="currentView === 'candle'" />
    <ScaleGame v-else-if="currentView === 'scale'" />
    <WheelGame v-else-if="currentView === 'wheel'" />
    <PosterView v-else-if="currentView === 'poster'" />
  </div>
</template>

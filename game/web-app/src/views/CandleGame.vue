<script setup>
import { ref, computed } from 'vue'
import { useGameState } from '../composables/useGameState.js'

const { userData, finishCandle } = useGameState()

const candleHeight = 320 // 蜡烛总高度 (px)
const cutY = ref(0) // 用户切割位置 (从顶部算起的 px)
const isDragging = ref(false)
const isRevealed = ref(false)
const containerRef = ref(null)

const guessRate = computed(() => {
  return Math.max(0, Math.min(1, cutY.value / candleHeight))
})

const remainingHeight = computed(() => {
  return candleHeight - cutY.value
})

const realCutY = computed(() => {
  return userData.dropRate * candleHeight
})

const accuracyLabel = computed(() => {
  const diff = guessRate.value - userData.dropRate
  if (Math.abs(diff) < 0.05) return { text: '🧠 人间清醒', color: '#2ecc71', sub: '您准确预判了痛苦的深度。' }
  if (diff < 0) return { text: '😇 没有自知之明', color: '#e74c3c', sub: '市场的刀比您想的要快得多。' }
  return { text: '😰 太悲观了', color: '#f1c40f', sub: '虽然很惨，但还没到您想的那么惨。' }
})

const onTouchStart = (e) => {
  if (isRevealed.value) return
  isDragging.value = true
  updateCut(e)
}

const onTouchMove = (e) => {
  if (!isDragging.value || isRevealed.value) return
  e.preventDefault()
  updateCut(e)
}

const onTouchEnd = () => {
  isDragging.value = false
}

const updateCut = (e) => {
  const container = containerRef.value
  if (!container) return
  const rect = container.getBoundingClientRect()
  const clientY = e.touches ? e.touches[0].clientY : e.clientY
  const y = Math.max(0, Math.min(candleHeight, clientY - rect.top))
  cutY.value = y
}

const reveal = () => {
  isRevealed.value = true
}

const next = () => {
  finishCandle(guessRate.value)
}
</script>

<template>
  <div class="px-5 py-6 min-h-[100dvh] flex flex-col">
    <!-- 标题 -->
    <div class="text-center mb-2 fade-up">
      <div class="text-xs font-medium tracking-widest" style="color:var(--color-muted)">第一关</div>
      <h2 class="text-2xl font-black mt-1">切蜡烛 🕯️</h2>
      <p class="text-sm mt-2" style="color:var(--color-muted)">
        这根蜡烛代表您的房产。<br>
        滑动切掉您认为已经<span style="color:var(--color-primary)">蒸发</span>的部分。
      </p>
    </div>

    <!-- 蜡烛区域 -->
    <div class="flex-1 flex flex-col items-center justify-center">
      <div class="relative" style="width:120px">
        <!-- 火焰 -->
        <div v-if="cutY < candleHeight * 0.95" class="candle-flame float-anim"></div>
        <!-- 烛芯 -->
        <div v-if="cutY < candleHeight * 0.95" class="candle-wick"></div>
        
        <!-- 蜡烛主体 (可触摸) -->
        <div
          ref="containerRef"
          class="candle-container"
          :style="{ height: candleHeight + 'px', width: '80px' }"
          @touchstart="onTouchStart"
          @touchmove.prevent="onTouchMove"
          @touchend="onTouchEnd"
          @mousedown="onTouchStart"
          @mousemove="onTouchMove"
          @mouseup="onTouchEnd"
          @mouseleave="onTouchEnd"
        >
          <!-- 已切掉部分 (透明) -->
          <div
            :style="{ height: cutY + 'px', background: 'rgba(231,76,60,.15)', borderRadius: '6px 6px 0 0' }"
          ></div>
          <!-- 剩余部分 (红色) -->
          <div
            class="candle-body"
            :style="{ height: remainingHeight + 'px' }"
          ></div>
          <!-- 切割线 -->
          <div v-if="!isRevealed" class="cut-line" :style="{ top: cutY + 'px' }"></div>
          <!-- 真实切割线 (揭示后) -->
          <div
            v-if="isRevealed"
            class="cut-line"
            :style="{
              top: realCutY + 'px',
              background: '#2ecc71',
              boxShadow: '0 0 12px rgba(46,204,113,.6)'
            }"
          ></div>
        </div>

        <!-- 百分比标签 -->
        <div
          class="absolute text-sm font-bold"
          :style="{
            top: cutY + 'px', left: '100px',
            transform: 'translateY(-50%)',
            color: 'var(--color-primary)',
          }"
        >
          -{{ (guessRate * 100).toFixed(0) }}%
        </div>
      </div>

      <!-- 揭示结果 -->
      <div v-if="isRevealed" class="text-center mt-6 fade-up">
        <div
          class="text-xl font-bold mb-1"
          :style="{ color: accuracyLabel.color }"
        >
          {{ accuracyLabel.text }}
        </div>
        <p class="text-sm" style="color:var(--color-muted)">{{ accuracyLabel.sub }}</p>
        <div class="mt-3 card text-center">
          <div class="text-xs" style="color:var(--color-muted)">真实跌幅</div>
          <div class="text-3xl font-black num-highlight mt-1">
            -{{ (userData.dropRate * 100).toFixed(1) }}%
          </div>
          <div class="text-xs mt-1" style="color:var(--color-muted)">
            您猜的: -{{ (guessRate * 100).toFixed(1) }}%
          </div>
        </div>
      </div>
    </div>

    <!-- 底部按钮 -->
    <div class="mt-auto pt-4">
      <button v-if="!isRevealed" @click="reveal" class="btn-primary pulse-glow">
        ✂️ 一刀下去
      </button>
      <button v-else @click="next" class="btn-primary">
        继续面对 →
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useGameState } from '../composables/useGameState.js'

const { userData, wheelPhrases, finishWheel } = useGameState()

const isSpinning = ref(false)
const result = ref(null)
const rotation = ref(0)

const segments = computed(() => {
  return wheelPhrases.map(p => {
    if (p.isReal && p.text.includes('??')) {
      const pct = Math.abs(userData.trendFactor * 100).toFixed(0)
      return { ...p, text: `明年再跌 ${pct}%` }
    }
    return { ...p }
  })
})

const segCount = computed(() => segments.value.length)
const segAngle = computed(() => 360 / segCount.value)

// SVG 辅助函数
const getSlicePath = (index) => {
  const cx = 150, cy = 150, r = 140
  const count = segCount.value
  const angle = 360 / count
  const startAngle = (index * angle - 90) * Math.PI / 180
  const endAngle = ((index + 1) * angle - 90) * Math.PI / 180
  const x1 = cx + r * Math.cos(startAngle)
  const y1 = cy + r * Math.sin(startAngle)
  const x2 = cx + r * Math.cos(endAngle)
  const y2 = cy + r * Math.sin(endAngle)
  const largeArc = angle > 180 ? 1 : 0
  return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`
}

const getTextTransform = (index) => {
  const cx = 150, cy = 150, r = 95
  const count = segCount.value
  const angle = 360 / count
  const midAngle = ((index + 0.5) * angle - 90) * Math.PI / 180
  const x = cx + r * Math.cos(midAngle)
  const y = cy + r * Math.sin(midAngle)
  const rotDeg = (index + 0.5) * angle
  return `translate(${x}, ${y}) rotate(${rotDeg})`
}

const spin = () => {
  if (isSpinning.value) return
  isSpinning.value = true

  const extraRotations = (5 + Math.random() * 3) * 360
  const targetAngle = Math.random() * 360
  const totalRotation = extraRotations + targetAngle

  rotation.value += totalRotation

  setTimeout(() => {
    const normalizedAngle = (360 - (rotation.value % 360)) % 360
    const segIndex = Math.floor(normalizedAngle / segAngle.value) % segCount.value
    result.value = segments.value[segIndex]
    isSpinning.value = false
  }, 3500)
}

const goToPoster = () => {
  finishWheel(result.value.text, result.value.isReal)
}
</script>

<template>
  <div class="px-5 py-6 min-h-[100dvh] flex flex-col">
    <!-- 标题 -->
    <div class="text-center mb-4 fade-up">
      <div class="text-xs font-medium tracking-widest" style="color:var(--color-muted)">第三关</div>
      <h2 class="text-2xl font-black mt-1">命运轮盘 🎡</h2>
      <p class="text-sm mt-2" style="color:var(--color-muted)">
        转动命运之轮<br>
        是<span style="color:#2ecc71">吉祥话</span>还是<span style="color:var(--color-primary)">残酷真相</span>？
      </p>
    </div>

    <!-- 轮盘区域 -->
    <div class="flex-1 flex flex-col items-center justify-center">
      <div class="relative" style="width:300px; height:300px">
        <!-- 指针 -->
        <div class="absolute top-0 left-1/2 -translate-x-1/2 -translate-y-2 z-10">
          <div style="
            width: 0; height: 0;
            border-left: 12px solid transparent;
            border-right: 12px solid transparent;
            border-top: 20px solid var(--color-primary);
            filter: drop-shadow(0 2px 4px rgba(0,0,0,.5));
          "></div>
        </div>

        <!-- 轮盘 SVG -->
        <svg
          viewBox="0 0 300 300"
          class="w-full h-full"
          :style="{
            transform: `rotate(${rotation}deg)`,
            transition: isSpinning ? 'transform 3.5s cubic-bezier(0.17, 0.67, 0.12, 0.99)' : 'none',
          }"
        >
          <g v-for="(seg, i) in segments" :key="i">
            <path
              :d="getSlicePath(i)"
              :fill="seg.color"
              stroke="rgba(0,0,0,.3)"
              stroke-width="1"
            />
            <text
              :transform="getTextTransform(i)"
              fill="white"
              font-size="11"
              font-weight="bold"
              text-anchor="middle"
              dominant-baseline="middle"
            >
              {{ seg.text }}
            </text>
          </g>
          <circle cx="150" cy="150" r="28" fill="#0f0f1a" stroke="rgba(255,255,255,.1)" stroke-width="2"/>
          <text x="150" y="150" fill="white" font-size="10" text-anchor="middle" dominant-baseline="middle" font-weight="bold">命运</text>
        </svg>
      </div>

      <!-- 结果 -->
      <div v-if="result" class="text-center mt-6 fade-up" style="width:100%">
        <div class="card" :style="{ borderColor: result.isReal ? 'rgba(231,76,60,.4)' : 'rgba(46,204,113,.3)' }">
          <div v-if="!result.isReal">
            <div class="text-2xl mb-1">🎊</div>
            <div class="text-lg font-bold" style="color:#2ecc71">{{ result.text }}</div>
            <p class="text-xs mt-2" style="color:var(--color-muted)">
              恭喜您获得了精神胜利法大奖。<br>
              <span style="color:var(--color-primary)">(现实: 跌势仍将持续)</span>
            </p>
          </div>
          <div v-else>
            <div class="text-2xl mb-1">💀</div>
            <div class="text-lg font-bold" style="color:var(--color-primary)">{{ result.text }}</div>
            <p class="text-xs mt-2" style="color:var(--color-muted)">
              很遗憾，您抽中了真相。
            </p>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部按钮 -->
    <div class="mt-auto pt-4">
      <button v-if="!result" @click="spin" :disabled="isSpinning" class="btn-primary pulse-glow">
        {{ isSpinning ? '命运旋转中...' : '🎰 转动命运之轮' }}
      </button>
      <button v-else @click="goToPoster" class="btn-primary">
        生成我的审判书 →
      </button>
    </div>
  </div>
</template>

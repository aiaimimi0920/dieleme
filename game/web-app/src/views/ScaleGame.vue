<script setup>
import { ref, computed, onMounted } from 'vue'
import { useGameState } from '../composables/useGameState.js'

const { userData, finishScale } = useGameState()

const revealIndex = ref(-1) // 逐条揭示
const allRevealed = ref(false)

const loss = computed(() => userData.lossAmount)
const items = computed(() => userData.scaleItems)

const revealNext = () => {
  if (revealIndex.value < items.value.length - 1) {
    revealIndex.value++
  } else {
    allRevealed.value = true
  }
}

// 总重量动画
const currentWeight = ref(0)
const targetWeight = computed(() => {
  return items.value
    .slice(0, revealIndex.value + 1)
    .reduce((sum, item) => sum + item.price * item.count, 0)
})
const weightPercent = computed(() => {
  if (loss.value === 0) return 0
  return Math.min(100, (currentWeight.value / loss.value) * 100)
})

const updateWeight = () => {
  const diff = targetWeight.value - currentWeight.value
  if (Math.abs(diff) > 100) {
    currentWeight.value += diff * 0.1
    requestAnimationFrame(updateWeight)
  } else {
    currentWeight.value = targetWeight.value
  }
}

onMounted(() => {
  // 自动开始逐条揭示
  let i = 0
  const timer = setInterval(() => {
    if (i < items.value.length) {
      revealIndex.value = i
      i++
      requestAnimationFrame(updateWeight)
    } else {
      allRevealed.value = true
      clearInterval(timer)
    }
  }, 800)
})
</script>

<template>
  <div class="px-5 py-6 min-h-[100dvh] flex flex-col">
    <!-- 标题 -->
    <div class="text-center mb-6 fade-up">
      <div class="text-xs font-medium tracking-widest" style="color:var(--color-muted)">第二关</div>
      <h2 class="text-2xl font-black mt-1">虚无天平 ⚖️</h2>
      <p class="text-sm mt-2" style="color:var(--color-muted)">
        您的亏损到底有多重？<br>
        让我们用<span style="color:var(--color-primary)">实物</span>来称量一下。
      </p>
    </div>

    <!-- 亏损金额 -->
    <div class="card text-center mb-6 fade-up-delay">
      <div class="text-xs" style="color:var(--color-muted)">总亏损金额</div>
      <div class="text-3xl font-black num-highlight mt-1">
        ¥ {{ loss.toLocaleString() }}
      </div>
      <div class="text-xs mt-1" style="color:var(--color-muted)">
        {{ userData.communityName }} · {{ userData.area }}m²
      </div>
    </div>

    <!-- 天平可视化 -->
    <div class="relative mb-6 fade-up-delay">
      <!-- 进度条 (Tilt) -->
      <div class="w-full h-3 rounded-full overflow-hidden" style="background:rgba(255,255,255,.06)">
        <div
          class="h-full rounded-full transition-all duration-700"
          :style="{
            width: weightPercent + '%',
            background: weightPercent >= 100 ? '#2ecc71' : 'linear-gradient(90deg, #e74c3c, #e67e22)'
          }"
        ></div>
      </div>
      <div class="flex justify-between mt-1 text-xs" style="color:var(--color-muted)">
        <span>⚖️ 0</span>
        <span v-if="weightPercent >= 100" style="color:#2ecc71">✓ 平衡</span>
        <span>¥{{ loss.toLocaleString() }}</span>
      </div>
    </div>

    <!-- 等价物清单 -->
    <div class="flex-1 space-y-3">
      <div
        v-for="(item, index) in items"
        :key="item.id"
        class="card flex items-center gap-4 transition-all duration-500"
        :style="{
          opacity: index <= revealIndex ? 1 : 0.15,
          transform: index <= revealIndex ? 'translateX(0)' : 'translateX(20px)',
        }"
      >
        <div class="text-3xl">{{ item.icon }}</div>
        <div class="flex-1">
          <div class="font-semibold text-sm">{{ item.name }}</div>
          <div class="text-xs" style="color:var(--color-muted)">¥{{ item.price.toLocaleString() }} / 个</div>
        </div>
        <div class="text-right">
          <div class="text-lg font-bold num-highlight">× {{ item.count }}</div>
          <div class="text-xs" style="color:var(--color-muted)">
            ¥{{ (item.price * item.count).toLocaleString() }}
          </div>
        </div>
      </div>
    </div>

    <!-- 扎心标语 -->
    <div v-if="allRevealed" class="text-center mt-6 fade-up">
      <div class="card" style="border-color: rgba(231,76,60,.3)">
        <p class="text-sm font-medium" style="color:var(--color-primary)">
          "以上这些东西加在一起，刚好等于您凭空蒸发的财富。"
        </p>
      </div>
    </div>

    <!-- 继续按钮 -->
    <div class="mt-auto pt-4">
      <button v-if="!allRevealed" @click="revealNext" class="btn-primary">
        继续添加砝码 ⚖️
      </button>
      <button v-else @click="finishScale" class="btn-primary">
        最后一关 →
      </button>
    </div>
  </div>
</template>

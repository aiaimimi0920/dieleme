<script setup>
import { ref, computed } from 'vue'
import { useGameState } from '../composables/useGameState.js'

const { userData, title, restart } = useGameState()

const posterRef = ref(null)
const sharing = ref(false)

const futureDropPct = computed(() => Math.abs(userData.trendFactor * 100).toFixed(0))
const futurePrice = computed(() => {
  const p = userData.currentPrice * (1 + userData.trendFactor)
  return Math.max(0, Math.round(p))
})
const futureLoss = computed(() => {
  return Math.round((userData.currentPrice - futurePrice.value) * userData.area)
})

const dateStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth()+1}月${d.getDate()}日`
})

const sharePoster = async () => {
  sharing.value = true
  try {
    const html2canvas = (await import('html2canvas')).default
    const canvas = await html2canvas(posterRef.value, {
      backgroundColor: '#0f0f1a',
      scale: 2,
    })
    const url = canvas.toDataURL('image/png')
    const link = document.createElement('a')
    link.download = `房价真相_${userData.communityName}.png`
    link.href = url
    link.click()
  } catch (e) {
    console.error('海报生成失败', e)
  }
  sharing.value = false
}
</script>

<template>
  <div class="px-5 py-6 min-h-[100dvh] flex flex-col">
    <!-- 标题 -->
    <div class="text-center mb-4 fade-up">
      <div class="text-xs font-medium tracking-widest" style="color:var(--color-muted)">最终审判</div>
      <h2 class="text-2xl font-black mt-1">牛马认证书 🐂🐴</h2>
    </div>

    <!-- 海报 -->
    <div ref="posterRef" class="poster-frame fade-up-delay">
      <!-- 头部标志 -->
      <div class="text-center mb-5">
        <div class="text-4xl mb-2">{{ title.emoji }}</div>
        <div class="text-xs tracking-widest" style="color:var(--color-muted)">房价真相 · 牛马认证</div>
      </div>

      <!-- 称号 -->
      <div class="text-center mb-5">
        <div
          class="inline-block px-4 py-1.5 rounded-full text-xs font-bold"
          style="background: rgba(231,76,60,.15); color: var(--color-primary); border: 1px solid rgba(231,76,60,.3)"
        >
          {{ title.name }}
        </div>
        <p class="text-xs mt-2" style="color:var(--color-muted)">{{ title.desc }}</p>
      </div>

      <!-- 数据卡片 -->
      <div class="space-y-3 mb-5">
        <!-- 小区 -->
        <div class="flex justify-between items-center py-2" style="border-bottom: 1px solid rgba(255,255,255,.06)">
          <span class="text-xs" style="color:var(--color-muted)">坐标</span>
          <span class="text-sm font-semibold">{{ userData.cityName }} · {{ userData.communityName }}</span>
        </div>
        <!-- 跌幅 -->
        <div class="flex justify-between items-center py-2" style="border-bottom: 1px solid rgba(255,255,255,.06)">
          <span class="text-xs" style="color:var(--color-muted)">总跌幅</span>
          <span class="text-lg font-black num-highlight">-{{ (userData.dropRate * 100).toFixed(1) }}%</span>
        </div>
        <!-- 亏损金额 -->
        <div class="flex justify-between items-center py-2" style="border-bottom: 1px solid rgba(255,255,255,.06)">
          <span class="text-xs" style="color:var(--color-muted)">蒸发金额</span>
          <span class="text-lg font-black num-highlight">¥{{ userData.lossAmount.toLocaleString() }}</span>
        </div>
        <!-- 等价物 (精简版) -->
        <div class="flex justify-between items-center py-2" style="border-bottom: 1px solid rgba(255,255,255,.06)">
          <span class="text-xs" style="color:var(--color-muted)">等价于</span>
          <span class="text-sm">
            <span v-for="item in userData.scaleItems.slice(0,3)" :key="item.id" class="mr-1">
              {{ item.icon }}×{{ item.count }}
            </span>
          </span>
        </div>
        <!-- 命运轮盘结果 -->
        <div class="flex justify-between items-center py-2" style="border-bottom: 1px solid rgba(255,255,255,.06)">
          <span class="text-xs" style="color:var(--color-muted)">命运之轮</span>
          <span class="text-sm font-semibold" :style="{ color: userData.wheelIsReal ? 'var(--color-primary)' : '#2ecc71' }">
            {{ userData.wheelPhrase }}
          </span>
        </div>
        <!-- 未来预警 -->
        <div class="flex justify-between items-center py-2">
          <span class="text-xs" style="color:var(--color-muted)">2027预测</span>
          <span class="text-sm">
            还将跌<span class="num-highlight ml-1">{{ futureDropPct }}%</span>
            (≈ ¥{{ futureLoss.toLocaleString() }})
          </span>
        </div>
      </div>

      <!-- 底部落款 -->
      <div class="text-center">
        <div class="text-xs" style="color:var(--color-muted)">
          {{ dateStr }} · 你的房还值多少？
        </div>
        <div class="text-xs mt-1" style="color:rgba(255,255,255,.2)">
          数据来源：全国司法拍卖公开信息
        </div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="mt-6 space-y-3 fade-up-delay2">
      <button @click="sharePoster" :disabled="sharing" class="btn-primary">
        {{ sharing ? '生成中...' : '📸 保存海报到相册' }}
      </button>
      <button @click="restart" class="btn-ghost">
        🔄 再来一次
      </button>
    </div>
  </div>
</template>

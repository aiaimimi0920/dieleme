import { ref, reactive, computed } from 'vue'

// ─── 全局游戏状态 (Singleton) ───
const currentView = ref('home') // home | candle | scale | wheel | poster

const userData = reactive({
  // 用户输入
  cityId: null,
  cityName: '',
  districtId: null,
  districtName: '',
  communityName: '',
  buyPrice: 0,      // 用户申报的购入单价
  area: 0,          // 面积

  // 数据计算得出
  currentPrice: 0,  // 当前法拍均价
  maxPrice: 0,      // 历史最高价
  dropRate: 0,      // 跌幅比率
  lossAmount: 0,    // 总亏损金额
  trendFactor: 0,   // 趋势因子

  // 游戏结果
  candleAccuracy: '', // 'optimistic' | 'pessimistic' | 'accurate'
  candleGuess: 0,
  scaleItems: [],     // 天平换算清单
  wheelPhrase: '',    // 命运轮盘结果
  wheelIsReal: false, // 是否抽中了真实预言
})

// ─── 等价物列表 ───
const equivalents = [
  { id: 'milk_tea', name: '喜茶', price: 20, icon: '🥤' },
  { id: 'iphone', name: 'iPhone 16 Pro', price: 9999, icon: '📱' },
  { id: 'ps5', name: 'PlayStation 5', price: 3500, icon: '🎮' },
  { id: 'lv_bag', name: 'LV Neverfull', price: 14000, icon: '👜' },
  { id: 'tesla_3', name: '特斯拉 Model 3', price: 245900, icon: '🚗' },
  { id: 'year_work', name: '打工人一年的汗水', price: 120000, icon: '💀' },
]

// ─── 轮盘配置 ───
const wheelPhrases = [
  { text: '时来运转', color: '#e74c3c', isReal: false },
  { text: '财源滚滚', color: '#e67e22', isReal: false },
  { text: '触底反弹', color: '#f1c40f', isReal: false },
  { text: '家和万事兴', color: '#2ecc71', isReal: false },
  { text: '平安喜乐', color: '#1abc9c', isReal: false },
  { text: '稳如泰山', color: '#3498db', isReal: false },
  { text: '未来可期', color: '#9b59b6', isReal: false },
  { text: '大吉大利', color: '#e91e63', isReal: false },
  // 真实预言槽位 (文字会在运行时动态替换)
  { text: '明年再跌 ??%', color: '#1a1a2e', isReal: true },
  { text: '还得跌', color: '#16213e', isReal: true },
]

// ─── 称号系统 ───
const getTitle = (dropRate) => {
  if (dropRate < 0.1) return { name: '微伤', emoji: '🤕', desc: '轻伤不下火线' }
  if (dropRate < 0.2) return { name: '白银投资者', emoji: '🥈', desc: '欢迎来到白银段位' }
  if (dropRate < 0.3) return { name: '韭菜本菜', emoji: '🥬', desc: '您就是传说中的韭菜' }
  if (dropRate < 0.4) return { name: '慈善家', emoji: '🎁', desc: '感谢您对开发商的无私捐赠' }
  if (dropRate < 0.5) return { name: '深潜员', emoji: '🤿', desc: '您已深入海底' }
  return { name: '传奇·高位站岗王', emoji: '👑', desc: '前无古人后无来者' }
}

// ─── 计算亏损等价物 ───
const calculateEquivalents = (lossAmount) => {
  const results = []
  let remaining = lossAmount
  for (const item of [...equivalents].reverse()) {
    const count = Math.floor(remaining / item.price)
    if (count > 0) {
      results.push({ ...item, count })
      remaining -= count * item.price
    }
  }
  return results
}

export function useGameState() {
  const title = computed(() => getTitle(userData.dropRate))

  const navigate = (view) => {
    currentView.value = view
  }

  const initUserData = (data) => {
    Object.assign(userData, data)
    // 计算亏损
    if (userData.buyPrice > userData.currentPrice) {
      userData.dropRate = (userData.buyPrice - userData.currentPrice) / userData.buyPrice
      userData.lossAmount = (userData.buyPrice - userData.currentPrice) * userData.area
    } else {
      userData.dropRate = 0
      userData.lossAmount = 0
    }
    userData.scaleItems = calculateEquivalents(userData.lossAmount)
  }

  const finishCandle = (guessRate) => {
    userData.candleGuess = guessRate
    const diff = Math.abs(guessRate - userData.dropRate)
    if (diff < 0.05) {
      userData.candleAccuracy = 'accurate'
    } else if (guessRate < userData.dropRate) {
      userData.candleAccuracy = 'optimistic'
    } else {
      userData.candleAccuracy = 'pessimistic'
    }
    currentView.value = 'scale'
  }

  const finishScale = () => {
    currentView.value = 'wheel'
  }

  const finishWheel = (phrase, isReal) => {
    userData.wheelPhrase = phrase
    userData.wheelIsReal = isReal
    currentView.value = 'poster'
  }

  const restart = () => {
    currentView.value = 'home'
    Object.assign(userData, {
      cityId: null, cityName: '', districtId: null, districtName: '',
      communityName: '', buyPrice: 0, area: 0, currentPrice: 0,
      maxPrice: 0, dropRate: 0, lossAmount: 0, trendFactor: 0,
      candleAccuracy: '', candleGuess: 0, scaleItems: [],
      wheelPhrase: '', wheelIsReal: false,
    })
  }

  return {
    currentView, userData, equivalents, wheelPhrases,
    title, navigate, initUserData,
    finishCandle, finishScale, finishWheel, restart,
    calculateEquivalents,
  }
}

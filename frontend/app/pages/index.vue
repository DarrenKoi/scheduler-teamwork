<script setup lang="ts">
const apiBase = 'http://localhost:5050'

const { data: jobs, refresh: refreshJobs } = await useFetch(`${apiBase}/api/jobs`)
const { data: systemStatus, refresh: refreshStatus } = await useFetch(`${apiBase}/api/status`)

const uploadModal = ref(false)
const uploadState = reactive({
  task: '',
  files: null as FileList | null,
  // Manual Config
  useManualConfig: false,
  scheduleType: 'interval',
  scheduleInterval: 30,
  scheduleUnit: 'minutes',
  scheduleCron: '* * * * *',
  entryPoint: 'main.py'
})
const uploading = ref(false)

const showExample = ref(false)
const exampleYaml = `name: "My Daily Task"
description: "Description of what this job does"
schedule:
  type: interval
  minutes: 30
entry_point: main.py
timeout: 3600`

const fileList = computed(() => {
  if (!uploadState.files) return []
  return Array.from(uploadState.files)
})

const hasJobYaml = computed(() => fileList.value.some(f => f.name === 'job.yaml'))
const hasPythonFile = computed(() => fileList.value.some(f => f.name.endsWith('.py')))
const availableEntryPoints = computed(() => fileList.value.filter(f => f.name.endsWith('.py')).map(f => f.name))

const isUploadValid = computed(() => {
  if (!uploadState.task || !hasPythonFile.value) return false
  if (hasJobYaml.value) return true
  if (uploadState.useManualConfig) {
      if (!uploadState.entryPoint) return false
      if (uploadState.scheduleType === 'interval' && uploadState.scheduleInterval <= 0) return false
      if (uploadState.scheduleType === 'cron' && !uploadState.scheduleCron) return false
      return true
  }
  return false
})

// Poll for updates
onMounted(() => {
    setInterval(() => {
        refreshJobs()
        refreshStatus()
    }, 2000)
})

// --- Computed Data ---

const activeJobs = computed(() => {
    if (!jobs.value) return []
    return (jobs.value as any[]).filter(j => j.last_status === 'running')
})

const upcomingJobs = computed(() => {
    if (!jobs.value) return []
    return (jobs.value as any[])
        .filter(j => j.next_run && j.next_run !== '-')
        .sort((a, b) => new Date(a.next_run).getTime() - new Date(b.next_run).getTime())
        .slice(0, 5)
})

const problemJobs = computed(() => {
    if (!jobs.value) return []
    return (jobs.value as any[])
        .filter(j => ['failed', 'timeout'].includes(j.last_status))
        .slice(0, 5)
})

const statusColor = computed(() => {
    const s = (systemStatus.value as any)?.status
    if (s === 'updating') return 'orange'
    if (s === 'running') return 'blue'
    return 'green'
})

// --- Actions ---

function copyExample() {
  navigator.clipboard.writeText(exampleYaml)
  alert("Example copied to clipboard!")
}

async function onUpload() {
  if (!uploadState.files || uploadState.files.length === 0) {
      alert("Please select files")
      return
  }
  
  uploading.value = true
  const formData = new FormData()
  formData.append('task', uploadState.task)
  
  for (let i = 0; i < uploadState.files.length; i++) {
    formData.append('files', uploadState.files[i])
  }

  if (uploadState.useManualConfig && !hasJobYaml.value) {
      formData.append('schedule_type', uploadState.scheduleType)
      formData.append('entry_point', uploadState.entryPoint)
      if (uploadState.scheduleType === 'interval') {
          formData.append(`schedule_${uploadState.scheduleUnit}`, uploadState.scheduleInterval.toString())
      } else {
          const parts = uploadState.scheduleCron.split(' ')
          if (parts.length >= 5) {
              formData.append('schedule_minute', parts[0])
              formData.append('schedule_hour', parts[1])
              formData.append('schedule_day', parts[2])
              formData.append('schedule_month', parts[3])
              formData.append('schedule_day_of_week', parts[4])
          }
      }
  }

  try {
    const res: any = await $fetch(`${apiBase}/api/upload`, {
      method: 'POST',
      body: formData
    })
    uploadModal.value = false
    uploadState.task = ''
    uploadState.files = null
    uploadState.useManualConfig = false
    uploadState.scheduleType = 'interval'
    alert(res.message || "Upload successful")
    refreshJobs()
  } catch (e: any) {
    alert('Upload failed: ' + e)
  } finally {
    uploading.value = false
  }
}

const updating = ref(false)
const editModal = ref(false)
const editState = reactive({
    task: '',
    name: '',
    description: '',
    entryPoint: '',
    scheduleType: 'interval',
    intervalValue: 30,
    intervalUnit: 'minutes',
    cronExpression: '* * * * *'
})

function openEditModal(job: any) {
    editState.task = job.task
    editState.name = job.name || job.task
    editState.description = job.description || ''
    editState.entryPoint = job.entry_point || 'main.py'
    editState.scheduleType = job.schedule_type || 'interval'
    const config = typeof job.schedule_config === 'string' ? JSON.parse(job.schedule_config) : job.schedule_config
    if (editState.scheduleType === 'interval') {
        const units = ['seconds', 'minutes', 'hours', 'days']
        for (const unit of units) {
            if (unit in config) {
                editState.intervalValue = config[unit]
                editState.intervalUnit = unit
                break
            }
        }
    } else {
        const parts = [config.minute || '*', config.hour || '*', config.day || '*', config.month || '*', config.day_of_week || '*']
        editState.cronExpression = parts.join(' ')
    }
    editModal.value = true
}

async function onUpdateConfig() {
    updating.value = true
    const newConfig: any = {
        name: editState.name,
        description: editState.description,
        entry_point: editState.entryPoint,
        schedule: { type: editState.scheduleType }
    }
    if (editState.scheduleType === 'interval') {
        newConfig.schedule[editState.intervalUnit] = parseInt(editState.intervalValue.toString())
    } else {
        const parts = editState.cronExpression.split(' ')
        if (parts.length >= 5) {
            newConfig.schedule = { type: 'cron', minute: parts[0], hour: parts[1], day: parts[2], month: parts[3], day_of_week: parts[4] }
        }
    }
    try {
        await $fetch(`${apiBase}/api/jobs/${editState.task}/config`, { method: 'POST', body: newConfig })
        editModal.value = false
        refreshJobs()
        alert('Configuration updated successfully')
    } catch (e: any) {
        alert('Failed to update config: ' + e)
    } finally {
        updating.value = false
    }
}

async function runJob(task: string) {
    await $fetch(`${apiBase}/api/run/${task}`, { method: 'POST' })
    refreshJobs()
}

async function toggleJob(task: string) {
    await $fetch(`${apiBase}/api/toggle/${task}`, { method: 'POST' })
    refreshJobs()
}
</script>

<template>
  <UContainer class="py-8">
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
      <div>
        <h1 class="text-2xl font-bold">Dashboard</h1>
        <p class="text-gray-500">Manage and monitor your Python jobs</p>
      </div>
      <div class="flex gap-2">
          <UButton icon="i-heroicons-plus" color="primary" @click="uploadModal = true">Add New Job</UButton>
      </div>
    </div>

    <!-- Status Banner -->
    <UAlert
      v-if="(systemStatus as any)?.status === 'updating'"
      icon="i-heroicons-exclamation-triangle"
      color="orange"
      variant="subtle"
      title="System Update Queued"
      description="New job files have been uploaded. The system will restart jobs when the current queue is empty."
      class="mb-6"
    />

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
        
        <!-- Left Column: Job List -->
        <div class="lg:col-span-2">
            <h2 class="text-lg font-semibold mb-4 flex items-center gap-2">
                <UIcon name="i-heroicons-list-bullet" /> All Jobs
            </h2>
            
            <div v-if="!jobs || (jobs as any[]).length === 0" class="space-y-6">
                <div class="text-center text-gray-500 py-12 bg-gray-50 rounded-xl border-2 border-dashed border-gray-200">
                    <UIcon name="i-heroicons-inbox" class="w-16 h-16 mx-auto mb-4 text-gray-300" />
                    <h3 class="text-xl font-semibold text-gray-900">Ready to automate?</h3>
                    <p class="mt-2 text-gray-500 max-w-sm mx-auto">No jobs are registered yet. Connect your Python scripts to start scheduling tasks.</p>
                    <div class="mt-6">
                        <UButton size="lg" icon="i-heroicons-plus" @click="uploadModal = true">Add Your First Job</UButton>
                    </div>
                </div>

                <!-- Getting Started Guide -->
                <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mt-8">
                    <UCard :ui="{ body: { padding: 'p-5' } }">
                        <template #header>
                            <div class="flex items-center gap-2 font-bold">
                                <UIcon name="i-heroicons-document-plus" class="text-primary" />
                                1. Prepare Your Files
                            </div>
                        </template>
                        <p class="text-sm text-gray-600 mb-4">Each job requires at least one Python file:</p>
                        <ul class="text-xs space-y-2 font-mono bg-gray-900 text-gray-300 p-3 rounded-lg">
                            <li class="flex items-center gap-2"><UIcon name="i-heroicons-document-text" class="text-green-400"/> main.py</li>
                            <li class="pl-4 text-gray-500 italic"># (Optional) job.yaml, data.csv, etc.</li>
                        </ul>
                    </UCard>

                    <UCard :ui="{ body: { padding: 'p-5' } }">
                        <template #header>
                            <div class="flex items-center gap-2 font-bold">
                                <UIcon name="i-heroicons-cloud-arrow-up" class="text-primary" />
                                2. Upload & Run
                            </div>
                        </template>
                        <div class="space-y-3 text-sm text-gray-600">
                            <p>Click <strong>Add New Job</strong> and enter a unique task name.</p>
                            <p>Upload your Python scripts and set the schedule directly in the UI.</p>
                            <p>The scheduler will automatically detect and register your job!</p>
                        </div>
                    </UCard>
                </div>
            </div>

            <div v-else class="space-y-3 p-2">
                <UCard v-for="job in (jobs as any[])" :key="job.id" :ui="{ body: { padding: 'p-4 sm:p-4' } }">
                    <div class="flex flex-col sm:flex-row justify-between items-start gap-4">
                        <div class="flex-1">
                            <div class="flex items-center gap-2">
                                <UIcon name="i-heroicons-document-text" class="text-gray-400" />
                                <h3 class="font-bold text-lg">{{ job.name || job.task }}</h3>
                                <UBadge size="xs" color="gray" variant="subtle">{{ job.task }}</UBadge>
                            </div>
                            <p class="text-sm text-gray-500 mt-1">{{ job.description }}</p>
                            
                            <div class="mt-3 flex flex-wrap gap-2 text-xs">
                                    <UBadge color="gray" variant="solid" icon="i-heroicons-clock">
                                    {{ job.schedule_type }}: {{ job.schedule_config }}
                                    </UBadge>
                            </div>
                        </div>
                        
                        <div class="flex flex-col items-end gap-3">
                            <UBadge :color="job.last_status === 'success' ? 'green' : job.last_status === 'failed' ? 'red' : job.last_status === 'running' ? 'blue' : 'gray'" size="md">
                                {{ job.last_status || 'Never Run' }}
                            </UBadge>
                            
                            <div class="flex items-center gap-2">
                                <UTooltip text="Toggle Enable/Disable">
                                    <UButton size="xs" :color="job.enabled ? 'red' : 'green'" variant="ghost" :icon="job.enabled ? 'i-heroicons-pause' : 'i-heroicons-play'" @click="toggleJob(job.task)" />
                                </UTooltip>
                                
                                <UTooltip text="Edit Configuration">
                                    <UButton size="xs" color="gray" variant="ghost" icon="i-heroicons-cog-6-tooth" @click="openEditModal(job)" />
                                </UTooltip>

                                <UTooltip text="Run Immediately">
                                    <UButton size="xs" color="primary" icon="i-heroicons-play-circle" @click="runJob(job.task)">Run</UButton>
                                </UTooltip>
                                
                                <UButton size="xs" color="gray" :to="`${apiBase}/runs?job_id=${job.id}`" target="_blank" icon="i-heroicons-clock">History</UButton>
                            </div>
                        </div>
                    </div>
                </UCard>
            </div>
        </div>

        <!-- Right Column: Widgets -->
        <div class="space-y-6">
            
            <!-- System Status -->
            <UCard>
                <template #header>
                    <div class="font-bold flex items-center gap-2">
                        <UIcon name="i-heroicons-server" /> System Status
                    </div>
                </template>
                <div class="flex items-center justify-between">
                    <span class="text-sm font-medium">State</span>
                    <UBadge :color="statusColor" variant="subtle" class="capitalize">
                        {{ (systemStatus as any)?.status || 'unknown' }}
                    </UBadge>
                </div>
                <div class="mt-4 grid grid-cols-2 gap-4 text-center">
                    <div class="bg-gray-50 p-2 rounded">
                        <div class="text-2xl font-bold">{{ (systemStatus as any)?.running_count || 0 }}</div>
                        <div class="text-xs text-gray-500">Running</div>
                    </div>
                    <div class="bg-gray-50 p-2 rounded">
                        <div class="text-2xl font-bold">{{ (systemStatus as any)?.pending_count || 0 }}</div>
                        <div class="text-xs text-gray-500">Pending Updates</div>
                    </div>
                </div>
            </UCard>

            <!-- Active Jobs -->
            <UCard v-if="activeJobs.length > 0">
                <template #header>
                    <div class="font-bold flex items-center gap-2 text-blue-600">
                        <UIcon name="i-heroicons-cpu-chip" /> Active Jobs
                    </div>
                </template>
                <ul class="space-y-2">
                    <li v-for="job in activeJobs" :key="job.id" class="flex justify-between items-center text-sm">
                        <span>{{ job.name || job.task }}</span>
                        <UIcon name="i-heroicons-arrow-path" class="animate-spin text-blue-500" />
                    </li>
                </ul>
            </UCard>

            <!-- Upcoming Jobs -->
            <UCard>
                <template #header>
                    <div class="font-bold flex items-center gap-2">
                        <UIcon name="i-heroicons-calendar-days" /> Upcoming Jobs
                    </div>
                </template>
                <ul class="space-y-3" v-if="upcomingJobs.length > 0">
                    <li v-for="job in upcomingJobs" :key="job.id" class="text-sm border-b pb-2 last:border-0">
                        <div class="font-medium">{{ job.name || job.task }}</div>
                        <div class="text-xs text-gray-500 flex justify-between mt-1">
                            <span class="text-primary">{{ job.next_run }}</span>
                        </div>
                    </li>
                </ul>
                <p v-else class="text-sm text-gray-500 text-center">No upcoming jobs</p>
            </UCard>
            
            <!-- Problem Jobs -->
            <UCard v-if="problemJobs.length > 0">
                <template #header>
                    <div class="font-bold flex items-center gap-2 text-red-600">
                        <UIcon name="i-heroicons-exclamation-circle" /> Recent Issues
                    </div>
                </template>
                <ul class="space-y-2">
                    <li v-for="job in problemJobs" :key="job.id" class="text-sm flex justify-between items-center">
                        <span>{{ job.name || job.task }}</span>
                        <UBadge color="red" size="xs" variant="soft">{{ job.last_status }}</UBadge>
                    </li>
                </ul>
            </UCard>

        </div>
    </div>

    <!-- Upload Modal -->
    <UModal v-model="uploadModal">
      <UCard :ui="{ body: { padding: 'p-6' } }">
        <template #header>
          <div class="flex justify-between items-center">
            <div class="text-lg font-bold flex items-center gap-2">
                <UIcon name="i-heroicons-cloud-arrow-up" class="text-primary" />
                Add New Job
            </div>
            <UButton color="gray" variant="ghost" icon="i-heroicons-x-mark" @click="uploadModal = false" />
          </div>
        </template>
        
        <form @submit.prevent="onUpload" class="space-y-6">
            <UFormGroup label="Task Name" help="Unique identifier for this job (cannot be changed later)">
                <UInput v-model="uploadState.task" placeholder="e.g. daily-data-sync" icon="i-heroicons-tag" required />
            </UFormGroup>

            <!-- Example Helper -->
            <div>
                <UButton 
                    :icon="showExample ? 'i-heroicons-chevron-up' : 'i-heroicons-light-bulb'" 
                    variant="subtle" 
                    size="xs" 
                    color="gray"
                    @click="showExample = !showExample"
                >
                    {{ showExample ? 'Hide Example' : 'Show job.yaml Example' }}
                </UButton>
                
                <div v-if="showExample" class="mt-2 relative">
                    <pre class="text-[10px] bg-gray-900 text-gray-300 p-3 rounded-lg overflow-x-auto font-mono">{{ exampleYaml }}</pre>
                    <UButton 
                        size="xs" 
                        color="gray" 
                        variant="ghost" 
                        class="absolute top-1 right-1" 
                        icon="i-heroicons-clipboard"
                        @click="copyExample"
                    />
                </div>
            </div>
            
            <UFormGroup label="Files" help="Select Python scripts and optional config files">
                <div 
                    class="border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer"
                    :class="fileList.length > 0 ? 'border-primary-200 bg-primary-50/30' : 'border-gray-200 bg-gray-50 hover:bg-gray-100'"
                    @click="$refs.fileInput.click()"
                >
                    <input 
                        ref="fileInput"
                        type="file" 
                        multiple 
                        @change="(e: any) => uploadState.files = e.target.files" 
                        class="hidden"
                    />
                    
                    <div v-if="fileList.length === 0" class="space-y-2">
                        <UIcon name="i-heroicons-document-arrow-up" class="w-10 h-10 mx-auto text-gray-400" />
                        <p class="text-sm font-medium text-gray-700">Click to browse or drag files here</p>
                        <p class="text-xs text-gray-500">Required: At least one .py file</p>
                    </div>
                    
                    <div v-else class="space-y-3 text-left">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-xs font-bold uppercase tracking-wider text-gray-500">{{ fileList.length }} files selected</span>
                            <UButton size="xs" color="red" variant="link" @click.stop="uploadState.files = null">Clear All</UButton>
                        </div>
                        <ul class="max-h-40 overflow-y-auto space-y-1 pr-2">
                            <li v-for="file in fileList" :key="file.name" class="flex items-center gap-2 text-sm py-1 border-b border-gray-100 last:border-0">
                                <UIcon :name="file.name.endsWith('.py') ? 'i-heroicons-document-text' : (file.name === 'job.yaml' ? 'i-heroicons-cog-6-tooth' : 'i-heroicons-document')" 
                                       :class="file.name.endsWith('.py') ? 'text-green-500' : (file.name === 'job.yaml' ? 'text-blue-500' : 'text-gray-400')" />
                                <span class="truncate flex-1">{{ file.name }}</span>
                                <span class="text-[10px] text-gray-400 font-mono">{{ (file.size / 1024).toFixed(1) }} KB</span>
                            </li>
                        </ul>
                    </div>
                </div>
            </UFormGroup>

            <!-- Validation Badges -->
            <div class="flex flex-wrap gap-2 pt-2" v-if="fileList.length > 0">
                <UBadge :color="hasJobYaml ? 'green' : 'gray'" variant="subtle" size="xs">
                    <UIcon :name="hasJobYaml ? 'i-heroicons-check-circle' : 'i-heroicons-document'" class="mr-1" />
                    job.yaml {{ hasJobYaml ? 'Found' : 'Optional' }}
                </UBadge>
                <UBadge :color="hasPythonFile ? 'green' : 'red'" variant="subtle" size="xs">
                    <UIcon :name="hasPythonFile ? 'i-heroicons-check-circle' : 'i-heroicons-x-circle'" class="mr-1" />
                    Python Script (.py)
                </UBadge>
            </div>

            <!-- Manual Configuration UI -->
            <div v-if="hasPythonFile && !hasJobYaml" class="bg-gray-50 p-4 rounded-lg border border-gray-200 space-y-4">
                <div class="flex items-center justify-between">
                    <h3 class="font-semibold text-sm text-gray-700 flex items-center gap-2">
                        <UIcon name="i-heroicons-cog-6-tooth" /> Configure Job
                    </h3>
                    <UToggle v-model="uploadState.useManualConfig" />
                </div>

                <div v-if="uploadState.useManualConfig" class="space-y-4 animate-in fade-in slide-in-from-top-2 duration-300">
                    <UFormGroup label="Entry Point" help="Script to execute">
                        <USelect v-model="uploadState.entryPoint" :options="availableEntryPoints" />
                    </UFormGroup>

                    <div class="grid grid-cols-2 gap-4">
                        <UFormGroup label="Schedule Type">
                            <USelect v-model="uploadState.scheduleType" :options="['interval', 'cron']" />
                        </UFormGroup>
                        
                        <div v-if="uploadState.scheduleType === 'interval'" class="flex gap-2 items-end">
                            <UFormGroup label="Every" class="flex-1">
                                <UInput v-model="uploadState.scheduleInterval" type="number" min="1" />
                            </UFormGroup>
                            <UFormGroup label="Unit" class="flex-1">
                                <USelect v-model="uploadState.scheduleUnit" :options="['seconds', 'minutes', 'hours', 'days']" />
                            </UFormGroup>
                        </div>
                        
                        <UFormGroup v-else label="Cron Expression" class="col-span-1">
                            <UInput v-model="uploadState.scheduleCron" placeholder="* * * * *" />
                        </UFormGroup>
                    </div>
                </div>
                <div v-else class="text-xs text-gray-500 italic">
                    Enable configuration to set schedule now, otherwise upload a job.yaml later.
                </div>
            </div>
            
            <div class="bg-blue-50 p-4 rounded-lg flex gap-3 items-start" v-if="!isUploadValid && fileList.length > 0">
                <UIcon name="i-heroicons-information-circle" class="w-5 h-5 text-blue-500 mt-0.5" />
                <div class="text-xs text-blue-700 space-y-1">
                    <p class="font-bold">Missing requirements:</p>
                    <ul class="list-disc pl-4">
                        <li v-if="!uploadState.task">Task name is required</li>
                        <li v-if="!hasJobYaml && !uploadState.useManualConfig">Enable configuration or include a <code>job.yaml</code></li>
                        <li v-if="!hasPythonFile">Include at least one <code>.py</code> script</li>
                    </ul>
                </div>
            </div>
            
            <div class="flex justify-end gap-2 mt-6">
                <UButton color="gray" variant="ghost" @click="uploadModal = false">Cancel</UButton>
                <UButton type="submit" :loading="uploading" :disabled="!isUploadValid" color="primary" block>
                    Create Job
                </UButton>
            </div>
        </form>
      </UCard>
    </UModal>

    <!-- Edit Modal -->
    <UModal v-model="editModal">
        <UCard :ui="{ body: { padding: 'p-6' } }">
            <template #header>
                <div class="flex justify-between items-center">
                    <h3 class="font-bold text-lg">Edit Job: {{ editState.name }}</h3>
                    <UButton color="gray" variant="ghost" icon="i-heroicons-x-mark" @click="editModal = false" />
                </div>
            </template>
            
            <form @submit.prevent="onUpdateConfig" class="space-y-4">
                <UFormGroup label="Description">
                    <UInput v-model="editState.description" />
                </UFormGroup>
                
                <UFormGroup label="Entry Point">
                    <UInput v-model="editState.entryPoint" />
                </UFormGroup>
                
                <UFormGroup label="Schedule Type">
                    <USelect v-model="editState.scheduleType" :options="['interval', 'cron']" />
                </UFormGroup>
                
                <div v-if="editState.scheduleType === 'interval'" class="flex gap-2">
                    <UFormGroup label="Value" class="flex-1">
                        <UInput v-model="editState.intervalValue" type="number" />
                    </UFormGroup>
                    <UFormGroup label="Unit" class="flex-1">
                        <USelect v-model="editState.intervalUnit" :options="['seconds', 'minutes', 'hours', 'days']" />
                    </UFormGroup>
                </div>
                
                <div v-else>
                    <UFormGroup label="Cron Expression">
                        <UInput v-model="editState.cronExpression" placeholder="* * * * *" />
                    </UFormGroup>
                </div>
                
                <div class="flex justify-end gap-2 mt-6">
                    <UButton color="gray" variant="ghost" @click="editModal = false">Cancel</UButton>
                    <UButton type="submit" color="primary" :loading="updating">Save Changes</UButton>
                </div>
            </form>
        </UCard>
    </UModal>
  </UContainer>
</template>

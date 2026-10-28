/**
 * Settings mode controller (header mode dropdown → "⚙️ Einstellungen").
 *
 * The form is rendered generically from the schema returned by `GET /api/settings`,
 * so new backend settings appear automatically. Values are saved via `PUT /api/settings`.
 */

interface SettingSchema {
  key: string;
  type: 'integer';
  default: number;
  min: number;
  max: number;
  group: string;
  label: string;
  description: string;
}

interface SettingsResponse {
  values: Record<string, number>;
  schema: SettingSchema[];
}

export class SettingsController {
  private form = document.getElementById('settings-form') as HTMLFormElement | null;
  private fields = document.getElementById('settings-fields') as HTMLDivElement | null;
  private status = document.getElementById('settings-status') as HTMLParagraphElement | null;
  private saveBtn = document.getElementById('settings-save-btn') as HTMLButtonElement | null;
  private resetBtn = document.getElementById('settings-reset-btn') as HTMLButtonElement | null;
  private schema: SettingSchema[] = [];
  private loaded = false;

  constructor() {
    this.form?.addEventListener('submit', (e) => {
      e.preventDefault();
      void this.save();
    });
    this.resetBtn?.addEventListener('click', () => this.resetToDefaults());
  }

  /** Called whenever the settings view becomes visible. */
  activate(): void {
    void this.load();
  }

  private setStatus(text: string, kind: 'info' | 'ok' | 'error' = 'info'): void {
    if (!this.status) return;
    this.status.textContent = text;
    this.status.dataset.kind = kind;
  }

  private async load(): Promise<void> {
    try {
      const res = await fetch('/api/settings');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as SettingsResponse;
      this.schema = data.schema;
      this.render(data.values);
      this.loaded = true;
      this.setStatus('');
    } catch (err) {
      this.setStatus(`Einstellungen konnten nicht geladen werden: ${(err as Error).message}`, 'error');
    }
  }

  private render(values: Record<string, number>): void {
    if (!this.fields) return;
    this.fields.replaceChildren();
    const groups = new Map<string, SettingSchema[]>();
    for (const entry of this.schema) {
      const list = groups.get(entry.group) ?? [];
      list.push(entry);
      groups.set(entry.group, list);
    }
    for (const [group, entries] of groups) {
      const fieldset = document.createElement('fieldset');
      fieldset.className = 'settings-group space-y-4';
      const legend = document.createElement('legend');
      legend.className = 'text-xs font-bold uppercase tracking-wider text-slate-300 mb-2';
      legend.textContent = group;
      fieldset.appendChild(legend);

      for (const entry of entries) {
        const wrapper = document.createElement('div');
        wrapper.className = 'settings-field space-y-1.5';

        const label = document.createElement('label');
        label.htmlFor = `setting-${entry.key}`;
        label.className = 'block text-sm font-semibold text-slate-100';
        label.textContent = entry.label;

        const input = document.createElement('input');
        input.type = 'number';
        input.id = `setting-${entry.key}`;
        input.name = entry.key;
        input.min = String(entry.min);
        input.max = String(entry.max);
        input.step = '1';
        input.required = true;
        input.value = String(values[entry.key] ?? entry.default);
        input.className =
          'settings-input w-32 bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-100 focus:outline-none focus:border-indigo-500';
        input.setAttribute('aria-describedby', `setting-${entry.key}-help`);
        input.addEventListener('input', () => this.setStatus(''));

        const help = document.createElement('p');
        help.id = `setting-${entry.key}-help`;
        help.className = 'text-xs text-slate-400 max-w-2xl';
        help.textContent = `${entry.description} (Standard: ${entry.default}, erlaubt: ${entry.min}–${entry.max})`;

        wrapper.append(label, input, help);
        fieldset.appendChild(wrapper);
      }
      this.fields.appendChild(fieldset);
    }
  }

  private collectValues(): Record<string, number> | null {
    const values: Record<string, number> = {};
    for (const entry of this.schema) {
      const input = document.getElementById(`setting-${entry.key}`) as HTMLInputElement | null;
      if (!input) continue;
      if (!input.checkValidity()) {
        input.reportValidity();
        this.setStatus(`${entry.label}: bitte eine ganze Zahl zwischen ${entry.min} und ${entry.max} eingeben.`, 'error');
        return null;
      }
      values[entry.key] = Number(input.value);
    }
    return values;
  }

  private async save(): Promise<void> {
    if (!this.loaded) return;
    const values = this.collectValues();
    if (!values) return;
    if (this.saveBtn) this.saveBtn.disabled = true;
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ values }),
      });
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}));
        throw new Error((detail as { detail?: string }).detail || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as SettingsResponse;
      this.render(data.values);
      this.setStatus('✓ Gespeichert. Gilt ab der nächsten Standardisierung.', 'ok');
    } catch (err) {
      this.setStatus(`Speichern fehlgeschlagen: ${(err as Error).message}`, 'error');
    } finally {
      if (this.saveBtn) this.saveBtn.disabled = false;
    }
  }

  private resetToDefaults(): void {
    for (const entry of this.schema) {
      const input = document.getElementById(`setting-${entry.key}`) as HTMLInputElement | null;
      if (input) input.value = String(entry.default);
    }
    this.setStatus('Standardwerte eingetragen – zum Übernehmen speichern.', 'info');
  }
}

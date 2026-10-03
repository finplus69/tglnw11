(() => {
  if (window.__teleWorkspaceLoaded) return;
  window.__teleWorkspaceLoaded = true;

  const panel = document.createElement('aside');
  panel.className = 'tele-workspace-panel';
  panel.innerHTML = `
    <div class="tele-workspace-title"><span>TW</span><strong>Tele Workspace</strong><button aria-label="ปิด">×</button></div>
    <div class="tele-workspace-safe">Safe mode: ส่วนขยายนี้ไม่ส่งข้อความและไม่เพิ่มสมาชิก</div>
    <div class="tele-workspace-group">กำลังเตรียมข้อมูลกลุ่ม…</div>
    <button class="tele-workspace-copy">คัดลอกคำสั่ง CLI</button>
  `;
  document.documentElement.appendChild(panel);

  const close = panel.querySelector('button[aria-label="ปิด"]');
  close.addEventListener('click', () => panel.remove());
  const groupLabel = panel.querySelector('.tele-workspace-group');
  const copy = panel.querySelector('.tele-workspace-copy');

  chrome.storage.sync.get({ group: '', limit: 1000 }, ({ group, limit }) => {
    groupLabel.textContent = group ? `กลุ่มที่บันทึก: ${group}` : 'ยังไม่ได้ตั้งค่ากลุ่มใน popup';
    copy.addEventListener('click', async () => {
      const target = group || '@your_group';
      await navigator.clipboard.writeText(`python tele.py export-members --group ${target} --output members-export.csv --limit ${limit}`);
      copy.textContent = 'คัดลอกแล้ว';
      setTimeout(() => { copy.textContent = 'คัดลอกคำสั่ง CLI'; }, 1800);
    });
  });
})();

document.addEventListener('DOMContentLoaded', () => {
  const picker = document.querySelector('#images');
  const preview = document.querySelector('#preview');
  if (picker && preview) {
    picker.addEventListener('change', () => {
      preview.innerHTML = '';
      const files = Array.from(picker.files).slice(0, 6);
      files.forEach((file, index) => {
        if (!file.type.startsWith('image/')) return;
        const wrapper = document.createElement('div');
        wrapper.className = 'preview-item';
        const image = document.createElement('img');
        image.src = URL.createObjectURL(file);
        image.alt = 'Selected image preview';
        const remove = document.createElement('button');
        remove.type = 'button';
        remove.className = 'preview-remove';
        remove.innerHTML = '&times;';
        remove.title = 'Remove image';
        remove.addEventListener('click', () => {
          const transfer = new DataTransfer();
          files.filter((_, fileIndex) => fileIndex !== index).forEach(remaining => transfer.items.add(remaining));
          picker.files = transfer.files;
          picker.dispatchEvent(new Event('change'));
        });
        wrapper.append(image, remove);
        preview.appendChild(wrapper);
      });
    });
  }
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  window.setTimeout(() => document.querySelectorAll('.alert').forEach(alert => alert.remove()), 5000);
});

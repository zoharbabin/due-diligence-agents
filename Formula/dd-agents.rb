class DdAgents < Formula
  include Language::Python::Virtualenv

  desc "AI-powered forensic due diligence analysis for M&A deal teams"
  homepage "https://github.com/zoharbabin/due-diligence-agents"
  url "https://files.pythonhosted.org/packages/66/ba/06542556873a8f98b7a27e24b6c50607ba85627083d3df75af238f142505/dd_agents-1.0.2.tar.gz"
  sha256 "672c072e7188612d645b0f4a32f7120226bb5e60b36e55dcaf06d9770ea6020f"
  license "Apache-2.0"

  depends_on "python@3.12"
  depends_on "tesseract"
  depends_on "pandoc"
  depends_on "poppler" # pdf2image needs pdfinfo/pdftoppm from poppler

  def install
    virtualenv_create(libexec, "python3.12")
    system libexec/"bin/python", "-m", "pip", "install", "--verbose", "#{buildpath}[ocr]"
    bin.install_symlink Dir[libexec/"bin/dd-agents"]

    # Pre-built wheels (e.g. pydantic-core) ship .so files as MH_DYLIB with
    # an LC_ID_DYLIB load command. Homebrew tries to rewrite the dylib ID to
    # a long absolute path, but the Mach-O header lacks padding for it.
    # Fix: convert MH_DYLIB (6) → MH_BUNDLE (8) and strip LC_ID_DYLIB,
    # since Python extensions are loaded via dlopen (bundle is correct).
    system libexec/"bin/python", "-c", <<~PYTHON, *Dir.glob(libexec/"lib/**/*.so")
      import struct, sys, os
      LC_ID_DYLIB = 0x0D
      for path in sys.argv[1:]:
          with open(path, 'r+b') as f:
              magic = struct.unpack('<I', f.read(4))[0]
              if magic != 0xfeedfacf:
                  continue
              f.seek(0)
              hdr = bytearray(f.read(32))
              filetype = struct.unpack_from('<I', hdr, 12)[0]
              if filetype != 6:
                  continue
              ncmds = struct.unpack_from('<I', hdr, 16)[0]
              sizeofcmds = struct.unpack_from('<I', hdr, 20)[0]
              # Read all load commands
              cmds_blob = bytearray(f.read(sizeofcmds))
              # Find and remove LC_ID_DYLIB
              offset, new_blob = 0, bytearray()
              removed_size = 0
              for _ in range(ncmds):
                  cmd, cmdsize = struct.unpack_from('<II', cmds_blob, offset)
                  if cmd == LC_ID_DYLIB:
                      removed_size = cmdsize
                  else:
                      new_blob += cmds_blob[offset:offset+cmdsize]
                  offset += cmdsize
              if removed_size == 0:
                  continue
              # Rewrite header: MH_BUNDLE, ncmds-1, sizeofcmds-removed
              struct.pack_into('<I', hdr, 12, 8)
              struct.pack_into('<I', hdr, 16, ncmds - 1)
              struct.pack_into('<I', hdr, 20, sizeofcmds - removed_size)
              f.seek(0)
              f.write(hdr)
              f.write(new_blob)
              f.write(b'\\x00' * removed_size)
          os.system(f'codesign --force --sign - "{path}" 2>/dev/null')
    PYTHON
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/dd-agents version")
  end
end

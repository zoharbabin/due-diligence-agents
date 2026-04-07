class DdAgents < Formula
  include Language::Python::Virtualenv

  desc "AI-powered forensic due diligence analysis for M&A deal teams"
  homepage "https://github.com/zoharbabin/due-diligence-agents"
  url "https://files.pythonhosted.org/packages/fa/18/c58dc589a5c075ff6e2c6f98c6f928c022715dd67c42e1eea23282dd9c4d/dd_agents-0.5.7.tar.gz"
  sha256 "f0e319167347b82327b9f3c859bf0611aa3868c19268b569be814a0a84b8bc37"
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

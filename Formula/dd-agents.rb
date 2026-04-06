class DdAgents < Formula
  include Language::Python::Virtualenv

  desc "AI-powered forensic due diligence analysis for M&A deal teams"
  homepage "https://github.com/zoharbabin/due-diligence-agents"
  url "https://files.pythonhosted.org/packages/65/dc/c7c07f660ba741c5bfd9535ae3d9d22122c0dc154da0fb3a5b78c9bcfe86/dd_agents-0.5.1.tar.gz"
  sha256 "435e732ea48c50f961feff3236e2e82f4c03eb5e261d749e3e73812a2f75cba9"
  license "Apache-2.0"

  depends_on "python@3.12"

  def install
    virtualenv_create(libexec, "python3.12")
    system libexec/"bin/python", "-m", "pip", "install", "--verbose", buildpath
    bin.install_symlink Dir[libexec/"bin/dd-agents"]
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/dd-agents version")
  end
end

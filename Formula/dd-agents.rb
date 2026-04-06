class DdAgents < Formula
  include Language::Python::Virtualenv

  desc "AI-powered forensic due diligence analysis for M&A deal teams"
  homepage "https://github.com/zoharbabin/due-diligence-agents"
  url "https://files.pythonhosted.org/packages/b7/44/0cd39409c5ecf1298ff6d19e952b51cd1190456297f068d5962eca3d53e7/dd_agents-0.4.3.tar.gz"
  sha256 "e1726a3264753f58d627fcde6b5ba726dcca180bb70c9813450a3f73d857b964"
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

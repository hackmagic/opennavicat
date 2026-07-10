class Opennavicat < Formula
  desc "CLI-native, AI-powered database management tool (Navicat alternative)"
  homepage "https://github.com/opennavicat/opennavicat"
  license "MIT"

  on_macos do
    if Hardware::CPU.intel?
      url "https://github.com/opennavicat/opennavicat/releases/latest/download/opennavicat-macos-x86_64.tar.gz"
      sha256 ""
    end
    if Hardware::CPU.arm?
      url "https://github.com/opennavicat/opennavicat/releases/latest/download/opennavicat-macos-arm64.tar.gz"
      sha256 ""
    end
  end

  def install
    bin.install "opennavicat"
  end

  test do
    assert_match "opennavicat", shell_output("#{bin}/opennavicat --version")
  end
end

# TheEntireWorld
Downloadable Tools for DCC and Content Creation Pipelines; Starting with Animation and Cinematic Exporter for Maya and Motionbuilder with imports into Unreal 5.5

Instructions for first time using:

1. inside of tools, there will be a .bat file for the version of Maya you use (2023 - 2025 officially tests) or the version of Motionbuilder you use (2023 - 2026 officially working). It is recommended to run the first time as this will make sure you have the requests module... you may also opt to run maya_setup.py directly or motionbuilder_setup.py respectively
   
2. After that point you should be able to open maya or motionbuilder vanilla without the bat file, and the tool should open up and prompt you to select a Uproject

3. You *Must* have an unreal project set up currently for the exports to be added and exported as the tool relies on valid skeleton assets for the rigs you want to export, and it has been developed for 5.5 (future updates will support more versions)
If you need help with getting skeletons in engine, feel free to reach out until I have a quick tutorial for this linked

4. This part is now automated when you select the uproject with the UI, you can ignore (Inside Unreal, there is one part that is needed if you want to have the sequence importer work with the Engine open)
  
5. This part is now automated when you select the uproject with the UI, you can ignore (Edit > Project Settings > Python > Startup Scripts > Add an Array Element > set the path for the new index to be whatever your local path of  //tools/unreal_tools/http_server.py is... on my PC this is C:/depot/tools/unreal_tools/http_server.py. If this is not there by default, you may have to Load the Python Scripting related Plugins)
   
6. I walk through the functionality and how to get this setup in a few vimeo videos, though some updates have happened since then to the UI and the setup... this part is defined there : https://vimeo.com/user58067839 ; https://vimeo.com/user58067839

7. Beyond that once you have the UI open, the videos above show how to use the interface and I will be adding a paper documentation shortly

8. The only thing we ask is that if you do use our tools in your production, that you credit our studio for your tooling support, to help get our name out there. Honor system, please don't abuse the help we provide without helping us in return :)

#To Launch tool

Using the bat files, you should have a menu in maya and motionbuilder on startup titled "The Entire World Tools" with a Sequence UI item in the menu... but if you prefer to run manually or on your own shelf:
from maya_tools.Cinematics.SequenceUI import sequence_ui
sequence_ui.show_animation_manager()



To test the tool, I have included Mannequin rigs I found online so the skeleton to test will already be included in your project once you open it up.
The rigs were found here, i recommend supporting them if you care to donate on their page: https://gumroad.com/d/27fecce80492ca58d194844412cc370b

They exist in /ArtSource/Rigs inside The download from GitHub
